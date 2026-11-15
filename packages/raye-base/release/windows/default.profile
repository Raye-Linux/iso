# What every Windows program gets, before its own profile adds to it. Made
# to run most programs and games: Direct3D 8 to 12 on Vulkan comes from
# the ready space (DXVK, vkd3d-proton), ntsync is used when the kernel has
# it, sound goes through PipeWire at its own latency, and the core fonts
# are the system's. A program with no profile of its own runs on this one
# alone, so it may show bugs a checked profile would not.
#
# env= only quiets the parts that would otherwise write logs next to the
# program or fill a terminal; the runner keeps Wine's own messages off.
name="Default"
env="DXVK_LOG_LEVEL=none DXVK_LOG_PATH=none VKD3D_DEBUG=none VKD3D_SHADER_DEBUG=none DXVK_NVAPI_LOG_LEVEL=none EGL_LOG_LEVEL=fatal"
