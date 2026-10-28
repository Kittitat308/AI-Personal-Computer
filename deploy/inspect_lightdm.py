import gi

gi.require_version("LightDM", "1")
from gi.repository import LightDM

for name in dir(LightDM.Greeter):
    if any(word in name for word in ("auth", "session", "respond", "connect")):
        print(name)
print("signals")
for signal in ("show-prompt", "show-message", "authentication-complete", "autologin-timer-expired"):
    print(signal, LightDM.Greeter.signal_lookup(signal, LightDM.Greeter))
