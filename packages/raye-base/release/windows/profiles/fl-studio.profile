# FL Studio. The installer and the app share one space. A short PipeWire
# buffer keeps latency low; FL Studio ASIO runs on top of it, and Raye
# ASIO is there for the lowest latency. Fonts come from the layer's own
# list now, so Microsoft's core fonts are no longer fetched.
name="FL Studio"
match="*flstudio* *fl_studio* *fl-studio* *fl?studio*"
verbs="vcrun2022 gdiplus"
env="PIPEWIRE_LATENCY=256/48000"
title="fl-studio"
