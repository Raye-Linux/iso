# Audio plugin installers (VST, VST3, CLAP). Double-clicked on their own
# they would get a space of their own, and FL Studio would never see what
# they install. space= sends them to FL Studio's space, with its settings.
# The file name sorts last on purpose: the runner takes the first profile
# that matches, so a program with its own profile is never caught by
# *vst* (TAL's MSIs are named installer_vst3_64.msi).
name="Audio plugins"
match="surge-xt-* dexed-* tal-* vital* *vst*"
space="fl-studio"
