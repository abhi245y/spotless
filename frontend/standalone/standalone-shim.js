/* Installed inside Spotify's module, after cG, dG, TG and uG are defined. */
(function installStandaloneAuth(BaseSessions, Ps5Sessions, SonyLinker, Session, done, root) {
    "use strict";
    function enabled() { return root.__spotifyStandaloneAuth === true; }
    function currentAuthenticated(handler, bridge) {
        var profile = handler.userProfileFetcher.getCurrentUser();
        var id = handler.userProfileFetcher.getCurrentUserId();
        return !!(bridge &&
            bridge === handler._bridgeSessionsHandler.sessionObservable.getState() &&
            typeof bridge.getAccessToken === "function" && bridge.transport &&
            typeof id === "string" && id.length && profile &&
            profile.id === id && bridge.userId === id);
    }
    var originalTryLinked = BaseSessions.prototype._tryLoginLinkedUser;
    BaseSessions.prototype._tryLoginLinkedUser = function () {
        if (!enabled()) return originalTryLinked.apply(this, arguments);
        this._latestLinkingError = null;
        // This reads native login state and follows the original token/profile path.
        // Failures propagate; no successful authentication is synthesized.
        return this._bridgeSessionsHandler.checkLoggedInUser();
    };
    var originalOnSession = BaseSessions.prototype.onBridgeSession;
    BaseSessions.prototype.onBridgeSession = function (bridge) {
        if (!enabled() || bridge === null) {
            return originalOnSession.apply(this, arguments);
        }
        if (bridge !== this._bridgeSessionsHandler.sessionObservable.getState()) {
            return Promise.resolve();
        }
        if (!currentAuthenticated(this, bridge)) {
            return Promise.reject(new Error("Standalone session lacks authenticated Spotify profile"));
        }
        var session = new Session(bridge, false, false, this._authGen.get,
            this._logout, this.userProfileFetcher);
        session.isStandaloneAuth = true;
        this._latestLinkingError = null;
        return this.sessionObservable.set(session).then(done);
    };
    var originalRetry = Ps5Sessions.prototype._retryLoginLinkedUserLoop;
    Ps5Sessions.prototype._retryLoginLinkedUserLoop = function () {
        if (!enabled()) return originalRetry.apply(this, arguments);
        this._latestLinkingError = null;
        return Promise.resolve();
    };
    var originalRegisterFocus = Ps5Sessions.prototype._registerOnFocusListenerOnce;
    Ps5Sessions.prototype._registerOnFocusListenerOnce = function () {
        if (!enabled()) return originalRegisterFocus.apply(this, arguments);
    };
    // Defense against stale callbacks or explicit account-link UI routes.
    ["get", "link", "unlink"].forEach(function (method) {
        var original = SonyLinker.prototype[method];
        SonyLinker.prototype[method] = function () {
            if (!enabled()) return original.apply(this, arguments);
            if (method === "get") return Promise.resolve(null);
            return Promise.reject(new Error("Sony account linking disabled in standalone mode"));
        };
    });
})(cG, dG, TG, uG, lG, window);
