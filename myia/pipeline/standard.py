"""Pre-made pipelines."""


from ..abstract import Context, abstract_inferrer_constructors
from ..ir import GraphManager
from ..prim import py_registry, vm_registry
from ..validate import (
    validate_abstract as default_validate_abstract,
    whitelist as default_whitelist,
)
from . import steps
from .pipeline import PipelineDefinition
from .resources import (
    BackendResource,
    ConverterResource,
    DebugVMResource,
    InferenceResource,
    Resources,
    scalar_object_map,
    standard_method_map,
    standard_object_map,
)

standard_resources = Resources.partial(
    manager=GraphManager.partial(),
    py_implementations=py_registry,
    method_map=standard_method_map,
    convert=ConverterResource.partial(
        object_map=standard_object_map,
    ),
    inferrer=InferenceResource.partial(
        constructors=abstract_inferrer_constructors,
        context_class=Context,
    ),
    backend=BackendResource.partial(),
    debug_vm=DebugVMResource.partial(
        implementations=vm_registry,
    ),
    operation_whitelist=default_whitelist,
    validate_abstract=default_validate_abstract,
    return_backend=False,
)


######################
# Pre-made pipelines #
######################


standard_pipeline = PipelineDefinition(
    resources=standard_resources,
    parse=steps.step_parse,
    resolve=steps.step_resolve,
    infer=steps.step_infer,
    specialize=steps.step_specialize,
    simplify_types=steps.step_simplify_types,
    opt=steps.step_opt,
    opt2=steps.step_opt2,
    cconv=steps.step_cconv,
    validate=steps.step_validate,
    compile=steps.step_compile,
    wrap=steps.step_wrap,
)


scalar_pipeline = standard_pipeline.configure({
    'resources.convert.object_map': scalar_object_map,
})


standard_debug_pipeline = PipelineDefinition(
    resources=standard_resources,
    parse=steps.step_parse,
    resolve=steps.step_resolve,
    infer=steps.step_infer,
    specialize=steps.step_specialize,
    simplify_types=steps.step_simplify_types,
    opt=steps.step_opt,
    opt2=steps.step_opt2,
    cconv=steps.step_cconv,
    validate=steps.step_validate,
    export=steps.step_debug_export,
    wrap=steps.step_wrap,
).configure({
    'resources.backend.name': False
})


scalar_debug_pipeline = standard_debug_pipeline.configure({
    'resources.convert.object_map': scalar_object_map
})


######################
# Pre-made utilities #
######################


scalar_parse = scalar_pipeline \
    .select('resources', 'parse', 'resolve') \
    .make_transformer('input', 'graph')


scalar_debug_compile = scalar_debug_pipeline \
    .select('resources', 'parse', 'resolve', 'export') \
    .make_transformer('input', 'output')
