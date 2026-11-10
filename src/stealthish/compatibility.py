"""One reviewed Patchright adaptation over its private pipe. No child-session API."""
from contextlib import contextmanager
import hashlib
from importlib.metadata import version

from .errors import StartupError
from .release import DRIVER_VERSION

SOURCE_SHA256 = "84aacb258ce8bb655f06f066c8e091dad29e2aa5eb68586e2fd747fcabd8f3cc"
IN_USE = False
DISABLED = (
    "AvoidUnnecessaryBeforeUnloadCheckSync,DestroyProfileOnBrowserClose,DialMediaRouteProvider,"
    "GlobalMediaControls,HttpsUpgrades,LensOverlay,PaintHolding,ThirdPartyStoragePartitioning,"
    "BlockOriginHeaderModificationOnRedirect,AvoidCorsURLLoaderRestartOnRedirect,Translate,"
    "AutoDeElevate,OptimizationHints,NetworkTimeServiceQuerying,AimEnabled,"
    "msForceBrowserSignIn,msEdgeUpdateLaunchServicesPreferredVersion"
)
GPU_ARGS = ["--enable-gpu", "--use-angle=vulkan", "--enable-features=Vulkan", "--disable-vulkan-surface"]

PATCHES = [(
'''      async _send(method2, params2) {
        return await this._session.send(method2, params2);
      }''',
'''      async _send(method2, params2) {
        if (method2 === "Stealthish.setIdentity") {
          this._session._connection._stealthishIdentity = params2;
          this._session._connection._stealthishErrors = [];
          const pages = [...this._session._connection._sessions.values()]
            .filter(session => session._stealthishTargetType === "page");
          await Promise.all(pages.map(session => session.send("Emulation.setUserAgentOverride", params2)));
          return {};
        }
        if (method2 === "Stealthish.identityStatus")
          return { errors: this._session._connection._stealthishErrors || [] };
        return await this._session.send(method2, params2);
      }'''), (
'''        const id = this._connection._rawSend(this._sessionId, method2, params2);
        return new Promise((resolve, reject) => {
          this._callbacks.set(id, { resolve, reject, error: new ProtocolError("error", method2) });
        });''',
'''        const identity = this._connection._stealthishIdentity;
        let configured;
        if (identity && method2 === "Emulation.setUserAgentOverride")
          params2 = { ...params2, ...identity };
        if (identity && method2 === "Runtime.runIfWaitingForDebugger")
          configured = this.send("Emulation.setUserAgentOverride", identity);
        const id = this._connection._rawSend(this._sessionId, method2, params2);
        const response = new Promise((resolve, reject) => {
          this._callbacks.set(id, { resolve, reject, error: new ProtocolError("error", method2) });
        });
        return configured ? Promise.all([configured, response]).then(values => values[1]) : response;'''), (
'''        const session = this._session.createChildSession(sessionId);
        assert(targetInfo.browserContextId''',
'''        const session = this._session.createChildSession(sessionId);
        session._stealthishTargetType = targetInfo.type;
        assert(targetInfo.browserContextId'''), (
'''        session.detach().catch(() => {
        });
      }
      _onDetachedFromTarget(payload)''',
'''        if (targetInfo.type === "shared_worker" && this._connection._stealthishIdentity) {
          session.send("Emulation.setUserAgentOverride", this._connection._stealthishIdentity)
            .then(() => session.send("Runtime.runIfWaitingForDebugger"))
            .catch(() => this._connection._stealthishErrors.push("SHARED_WORKER_IDENTITY"));
          return;
        }
        session.detach().catch(() => {
        });
      }
      _onDetachedFromTarget(payload)'''),
]


def adapt_driver(data: bytes) -> bytes:
    """Used only by explicit release preparation, never at browser startup."""
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise StartupError("INCOMPATIBLE_DRIVER")
    source = data.decode()
    for before, after in PATCHES:
        if source.count(before) != 1:
            raise StartupError("INCOMPATIBLE_DRIVER")
        source = source.replace(before, after, 1)
    return source.encode()


@contextmanager
def select_driver(release):
    global IN_USE
    import patchright._impl._transport as transport
    if IN_USE:
        raise StartupError("SESSION_BUSY")
    if version("patchright") != DRIVER_VERSION:
        raise StartupError("INCOMPATIBLE_DRIVER")
    IN_USE = True
    original = transport.compute_driver_executable
    transport.compute_driver_executable = lambda: (
        str(release.node), str(release.root / "driver/package/cli.js")
    )
    try:
        yield
    finally:
        transport.compute_driver_executable = original
        IN_USE = False


def identity_payload(native):
    hints = native["clientHints"]
    ua = native["userAgent"]
    if ua.count("HeadlessChrome/") != 1 or not all(
        hints.get(key) for key in ("fullVersionList", "uaFullVersion", "bitness")
    ):
        raise StartupError("INCOMPATIBLE_DRIVER")
    metadata = {key: hints[key] for key in ("brands", "fullVersionList", "platform",
        "platformVersion", "architecture", "bitness", "model", "mobile", "wow64", "formFactors")}
    metadata["fullVersion"] = hints["uaFullVersion"]
    return {"userAgent": ua.replace("HeadlessChrome/", "Chrome/"),
            "platform": native["platform"], "userAgentMetadata": metadata}


def launch_options(release, payload=None, *, headless=True):
    options = {"executable_path": str(release.executable), "headless": True,
               "chromium_sandbox": True, "no_viewport": True,
               "args": ["--window-size=1440,1000", "--screen-info={1920x1080}", *GPU_ARGS],
               "ignore_default_args": ["--enable-unsafe-swiftshader"]}
    if not headless:
        # Explicit human access uses the real desktop. Keep the measured
        # headless branch unchanged; do not use its display/GPU overrides here.
        options["headless"] = False
        options["args"] = ["--window-size=1440,1000"]
    if payload:
        options["ignore_default_args"].append("--disable-features=" + DISABLED)
        features = ",".join(x for x in DISABLED.split(",") if x != "ThirdPartyStoragePartitioning")
        options["args"] += ["--user-agent=" + payload["userAgent"],
                            "--disable-features=" + features + ",UACHOverrideBlank"]
    return options
