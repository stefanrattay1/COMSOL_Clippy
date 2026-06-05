"""Lazy ``mph`` runtime wrapper for inspecting and editing COMSOL models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .plan import SaveTarget, WorkflowPlan, merge_save_targets, validate_plan_against_snapshot


class WorkflowRuntimeError(RuntimeError):
    """Raised for recoverable workflow/runtime failures."""


@dataclass(frozen=True)
class ModelSnapshot:
    """Serializable summary of a COMSOL model."""

    name: str
    file: str | None
    version: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)
    components: list[str] = field(default_factory=list)
    geometries: list[str] = field(default_factory=list)
    physics: list[str] = field(default_factory=list)
    multiphysics: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    meshes: list[str] = field(default_factory=list)
    studies: list[str] = field(default_factory=list)
    solutions: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    problems: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowExecutionResult:
    """Result summary from a workflow execution."""

    plan: WorkflowPlan
    action_summaries: list[str]
    evaluations: dict[str, Any] = field(default_factory=dict)
    saved_to: str | None = None
    snapshot: ModelSnapshot | None = None
    dry_run: bool = False
    validation_warnings: list[str] = field(default_factory=list)
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "plan": {
                "goal": self.plan.goal,
                "notes": self.plan.notes,
                "actions": [{"kind": a.kind, "args": a.args} for a in self.plan.actions],
                "save": {
                    "enabled": self.plan.save.enabled,
                    "path": self.plan.save.path,
                    "format": self.plan.save.format,
                },
            },
            "action_summaries": list(self.action_summaries),
            "evaluations": self.evaluations,
            "saved_to": self.saved_to,
            "dry_run": self.dry_run,
            "validation_warnings": list(self.validation_warnings),
            "attempts": self.attempts,
        }
        if self.snapshot is not None:
            payload["snapshot"] = self.snapshot.to_dict()
        return payload


class MPHRuntime:
    """Thin wrapper around the optional ``mph`` package.

    The import is delayed until first use so the default test path stays free of
    COMSOL/JPype requirements.
    """

    def __init__(
        self,
        *,
        cores: int | None = None,
        version: str | None = None,
        client_factory: Callable[[int | None, str | None], Any] | None = None,
    ):
        self.cores = cores
        self.version = version
        self._client = None
        self._client_factory = client_factory or self._default_client_factory

    @property
    def client(self):
        if self._client is None:
            self._client = self._client_factory(self.cores, self.version)
            caching = getattr(self._client, "caching", None)
            if callable(caching):
                try:
                    caching(True)
                except Exception:
                    pass
        return self._client

    def load_model(self, path: str | Path):
        model_path = Path(path).expanduser().resolve()
        if not model_path.exists():
            raise FileNotFoundError(f"COMSOL model not found: {model_path}")
        return self.client.load(str(model_path))

    def create_model(self, name: str | None = None):
        create = getattr(self.client, "create", None)
        if not callable(create):
            raise WorkflowRuntimeError("mph client does not expose create()")
        return create(name) if name else create()

    def release_model(self, model) -> None:
        remove = getattr(self.client, "remove", None)
        if callable(remove):
            try:
                remove(model)
            except Exception:
                pass

    def shutdown(self) -> None:
        if self._client is None:
            return
        clear = getattr(self._client, "clear", None)
        if callable(clear):
            try:
                clear()
            finally:
                self._client = None
        else:
            self._client = None

    def snapshot(self, model) -> ModelSnapshot:
        return ModelSnapshot(
            name=_safe_call(model, "name") or "",
            file=_safe_call(model, "file"),
            version=_safe_call(model, "version"),
            parameters=_safe_call(model, "parameters") or {},
            descriptions=_safe_call(model, "descriptions") or {},
            components=_names(model, "components"),
            geometries=_names(model, "geometries"),
            physics=_names(model, "physics"),
            multiphysics=_names(model, "multiphysics"),
            materials=_names(model, "materials"),
            meshes=_names(model, "meshes"),
            studies=_names(model, "studies"),
            solutions=_names(model, "solutions"),
            datasets=_names(model, "datasets"),
            exports=_names(model, "exports"),
            modules=_names(model, "modules"),
            problems=list(_safe_call(model, "problems") or []),
        )

    def apply_plan(
        self,
        model,
        plan: WorkflowPlan,
        *,
        base_dir: str | Path | None = None,
        save_target: SaveTarget | None = None,
        dry_run: bool = False,
        strict: bool = False,
    ) -> WorkflowExecutionResult:
        base = _default_base_dir(model, base_dir)
        effective_save = merge_save_targets(plan.save, save_target)
        action_summaries: list[str] = []
        evaluations: dict[str, Any] = {}
        geometry_context: dict[str, dict[str, Any]] = {}

        # Preflight: validate plan references against the model as it is now. This
        # runs for both real and dry runs so a dry run is a usable preflight.
        entry_snapshot = self.snapshot(model)
        validation_warnings = validate_plan_against_snapshot(plan, entry_snapshot)
        if validation_warnings and strict:
            raise WorkflowRuntimeError(
                "plan failed validation:\n" + "\n".join(validation_warnings)
            )

        for index, action in enumerate(plan.actions, start=1):
            action_summaries.append(f"{index}. {action.summary()}")
            if dry_run:
                continue

            args = action.args
            if action.kind == "set_parameter":
                model.parameter(args["name"], args["value"])
                if "description" in args and args["description"] is not None:
                    model.description(args["name"], args["description"])
            elif action.kind == "set_property":
                model.property(args["node"], args["name"], args["value"])
            elif action.kind == "create_node":
                model.create(args["node"], *list(args["arguments"]))
            elif action.kind == "create_rectangle":
                from .builders import create_rectangle

                node = create_rectangle(
                    model,
                    f"geometries/{args['geometry']}",
                    label=str(args["label"]),
                    pos=tuple(args["pos"]),
                    size=tuple(args["size"]),
                )
                geometry_context.setdefault(str(args["geometry"]), {}).setdefault("features", {})[
                    str(args["label"])
                ] = node
            elif action.kind == "create_difference":
                from .builders import create_difference

                features = geometry_context.get(str(args["geometry"]), {}).get("features", {})
                primary = features.get(str(args["primary"]), args["primary"])
                subtract = [features.get(str(item), item) for item in args["subtract"]]
                node = create_difference(
                    model,
                    f"geometries/{args['geometry']}",
                    label=str(args["label"]),
                    primary=primary,
                    subtract=subtract,
                )
                geometry_context.setdefault(str(args["geometry"]), {}).setdefault("features", {})[
                    str(args["label"])
                ] = node
            elif action.kind == "create_bell_oven_geometry":
                from .builders import build_bell_oven_geometry

                geometry_context[str(args["geometry"])] = build_bell_oven_geometry(model, args)
            elif action.kind == "remove_node":
                model.remove(args["node"])
            elif action.kind == "import_file":
                import_path = _resolve_path(args["path"], base)
                model.import_(args["node"], str(import_path))
            elif action.kind == "export_file":
                target = args.get("node")
                export_path = args.get("path")
                resolved = _resolve_path(export_path, base, create_parent=True) if export_path else None
                model.export(target, str(resolved) if resolved else None)
            elif action.kind == "build_geometry":
                model.build(args.get("geometry"))
            elif action.kind == "apply_fillet":
                from .builders import apply_fillet

                apply_fillet(model, args, geometry_context.get(str(args["geometry"])))
            elif action.kind == "apply_chamfer":
                from .builders import apply_chamfer

                apply_chamfer(model, args, geometry_context.get(str(args["geometry"])))
            elif action.kind == "defeature_geometry":
                from .builders import defeature_geometry

                defeature_geometry(model, args, geometry_context.get(str(args["geometry"])))
            elif action.kind == "round_coil_edges":
                from .builders import round_coil_edges

                round_coil_edges(model, args, geometry_context.get(str(args["geometry"])))
            elif action.kind == "run_mesh":
                model.mesh(args.get("mesh"))
            elif action.kind == "solve":
                model.solve(args.get("study"))
            elif action.kind == "evaluate":
                eval_kwargs = {
                    key: args[key]
                    for key in ("unit", "dataset", "inner", "outer")
                    if key in args and args[key] is not None
                }
                result = model.evaluate(args["expression"], **eval_kwargs)
                alias = args.get("alias") or f"evaluation_{len(evaluations) + 1}"
                evaluations[str(alias)] = result
            elif action.kind == "rename_model":
                model.rename(args["name"])
            elif action.kind == "clear_results":
                model.clear()
            elif action.kind == "reset_history":
                model.reset()
            else:
                raise WorkflowRuntimeError(f"unsupported workflow action at runtime: {action.kind}")

        saved_to = None
        if not dry_run and effective_save.requested:
            saved_to = self._save_model(model, effective_save, base)

        snapshot = entry_snapshot if dry_run else self.snapshot(model)
        return WorkflowExecutionResult(
            plan=plan,
            action_summaries=action_summaries,
            evaluations=evaluations,
            saved_to=saved_to,
            snapshot=snapshot,
            dry_run=dry_run,
            validation_warnings=validation_warnings,
        )

    def _save_model(self, model, save_target: SaveTarget, base_dir: Path) -> str | None:
        if save_target.path is None:
            model.save(format=save_target.format)
            return _safe_call(model, "file")
        save_path = _resolve_path(save_target.path, base_dir, create_parent=True)
        model.save(str(save_path), format=save_target.format)
        return str(save_path)

    @staticmethod
    def _default_client_factory(cores: int | None, version: str | None):
        try:
            import mph  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised via error path only
            raise WorkflowRuntimeError(
                "The optional 'mph' package is not installed. Install it with `pip install -e .[workflow]` "
                "inside an environment that also has COMSOL available."
            ) from exc

        kwargs = {}
        if cores is not None:
            kwargs["cores"] = cores
        if version is not None:
            kwargs["version"] = version
        start = getattr(mph, "start", None)
        if callable(start):
            return start(**kwargs)
        client_cls = getattr(mph, "Client", None)
        if client_cls is None:
            raise WorkflowRuntimeError("The installed 'mph' package does not expose start() or Client().")
        return client_cls(**kwargs)


def _default_base_dir(model, base_dir: str | Path | None) -> Path:
    if base_dir is not None:
        return Path(base_dir).expanduser().resolve()
    model_file = _safe_call(model, "file")
    if model_file:
        return Path(model_file).expanduser().resolve().parent
    return Path.cwd()


def _resolve_path(
    raw_path: str | Path,
    base_dir: Path,
    *,
    create_parent: bool = False,
) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    path = path.resolve()
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _safe_call(model, name: str):
    fn = getattr(model, name, None)
    if not callable(fn):
        return None
    try:
        return fn()
    except TypeError:
        return None


def _names(model, method: str) -> list[str]:
    value = _safe_call(model, method)
    if value is None:
        return []
    if isinstance(value, dict):
        return sorted(str(key) for key in value)
    return sorted(str(item) for item in value)