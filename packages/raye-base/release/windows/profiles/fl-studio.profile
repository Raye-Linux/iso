# FL Studio. The installer and the app share one space. A short PipeWire
# buffer keeps latency low; FL Studio ASIO runs on top of it.
name="FL Studio"
match="*flstudio* *fl_studio* *fl-studio* *fl?studio*"
verbs="corefonts vcrun2022 gdiplus"
env="PIPEWIRE_LATENCY=256/48000"
