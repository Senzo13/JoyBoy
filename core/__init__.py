"""
Core package — organized into subpackages.

Subpackages:
  core.ai          — AI intelligence (router, detection, prompts)
  core.generation  — Image/video generation pipeline
  core.models      — Model management and registry
  core.backends    — External integrations (GGUF, Ollama, search)
  core.infra       — Infrastructure utilities (logging, API, decoders)

Backward compatibility:
  Old imports like 'from core.processing import X' still work
  thanks to the alias system below.
"""
import sys
from types import ModuleType

_ALIASES = {
    # Models (core.models.__init__ handles 'core.models' itself)
    'core.model_manager': 'core.models.manager',
    'core.model_registry': 'core.models.registry',
    'core.video_loader': 'core.models.video_loader',
    'core.preload': 'core.models.preload',
    'core.vram_manager': 'core.models.vram',
    # Generation
    'core.processing': 'core.generation.processing',
    'core.segmentation': 'core.generation.segmentation',
    'core.body_estimation': 'core.generation.body_estimation',
    'core.face_restore': 'core.generation.face_restore',
    'core.florence': 'core.generation.florence',
    'core.food_vision': 'core.generation.food_vision',
    'core.image_context': 'core.generation.image_context',
    'core.video_optimizations': 'core.generation.video_optimizations',
    # AI
    'core.detection_ai': 'core.ai.detection_ai',
    'core.prompt_ai': 'core.ai.prompt_ai',
    'core.smart_router': 'core.ai.smart_router',
    'core.router_rules': 'core.ai.router_rules',
    'core.suggestions': 'core.ai.suggestions',
    'core.utility_ai': 'core.ai.utility_ai',
    # Backends
    'core.gguf_backend': 'core.backends.gguf_backend',
    'core.sdnq_backend': 'core.backends.sdnq_backend',
    'core.ollama_service': 'core.backends.ollama_service',
    'core.web_search': 'core.backends.web_search',
    'core.terminal_brain': 'core.backends.terminal_brain',
    'core.workspace_tools': 'core.backends.workspace_tools',
    # Infra
    'core.api_helpers': 'core.infra.api_helpers',
    'core.log_utils': 'core.infra.log_utils',
    'core.tunnel_service': 'core.infra.tunnel_service',
    'core.taehv_decode': 'core.infra.taehv_decode',
    'core.turbo_vaed_decode': 'core.infra.turbo_vaed_decode',
}


class _AliasModule(ModuleType):
    """Lazy module proxy that loads the real module on first attribute access."""

    def __init__(self, alias_name, real_name):
        super().__init__(alias_name)
        self._real_name = real_name

    def __getattr__(self, name):
        # Don't trigger lazy loading for dunder attributes (avoids circular imports
        # when torch/inspect probes __file__, __path__, __spec__, etc.)
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        import importlib
        real_mod = importlib.import_module(self._real_name)
        # Replace this proxy with the real module in sys.modules
        sys.modules[self.__name__] = real_mod
        return getattr(real_mod, name)


# Register lazy aliases so old import paths still work
for _alias, _real in _ALIASES.items():
    sys.modules[_alias] = _AliasModule(_alias, _real)
