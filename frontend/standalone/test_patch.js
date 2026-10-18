"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "..", "spotifytv.js"), "utf8");
const patched = fs.readFileSync(path.join(__dirname, "spotifytv.standalone.js"), "utf8");
const shim = fs.readFileSync(path.join(__dirname, "standalone-shim.js"), "utf8");

function originalMethod(name, next) {
    const prefix = "n." + name + "=";
    const start = source.indexOf(prefix) + prefix.length;
    assert.ok(start >= prefix.length);
    return source.slice(start, source.indexOf(",n." + next + "=", start));
}
function harness(mode = true) {
    const counts = { get: 0, link: 0, unlink: 0, nativeCheck: 0, retry: 0,
        nativeLogout: 0, scope: 0, focus: 0 };
    function Base() {}
    function Ps5() {}
    Ps5.prototype = Object.create(Base.prototype);
    function Linker() {}
    Linker.prototype.get = function () { counts.get++; return Promise.resolve(null); };
    Linker.prototype.link = function () { counts.link++; return Promise.resolve(true); };
    Linker.prototype.unlink = function () { counts.unlink++; return Promise.resolve(true); };
    function Session(bridge, linked, guest, auth, logout, fetcher) {
        Object.assign(this, { bridgeSession: bridge, isLinked: linked, isGuest: guest,
            getAccessToken: bridge.getAccessToken, transport: bridge.transport,
            userProfileFetcher: fetcher });
        this.logout = () => logout(this);
    }
    const root = { __spotifyStandaloneAuth: mode };
    const context = vm.createContext({ cG: Base, dG: Ps5, TG: Linker, uG: Session,
        lG() {}, window: root, Promise, Error, Ot: { capture() {} },
        WB: (unused, input) => input, KB() {}, sl: x => x !== undefined });
    Base.prototype.onBridgeSession = vm.runInContext("(" + originalMethod("onBridgeSession", "_resolveBridgeSession") + ")", context);
    Base.prototype._tryLoginLinkedUser = vm.runInContext("(" + originalMethod("_tryLoginLinkedUser", "poke") + ")", context);
    Base.prototype._logout = vm.runInContext("(" + originalMethod("_logout", "logout") + ")", context);
    Ps5.prototype._retryLoginLinkedUserLoop = function (error) { counts.retry++; return Promise.resolve(error); };
    Ps5.prototype._registerOnFocusListenerOnce = function () { counts.focus++; };
    vm.runInContext(shim, context);
    const bridge = { userId: "validated-user", transport: {}, getAccessToken() {},
        logout() { counts.nativeLogout++; return Promise.resolve(); } };
    let nativeState = bridge;
    let state;
    const changes = [];
    const handler = new Ps5();
    Object.assign(handler, {
        _latestLinkingError: "old-sony-error", isValidatingStoredCredentials: false,
        userProfileFetcher: { getCurrentUser: () => ({ id: "validated-user" }),
            getCurrentUserId: () => "validated-user" },
        _authGen: { get() {} }, _internalLinking: new Linker(),
        sessionObservable: {
            getState: () => state,
            set(value) { state = value; changes.push(value); return Promise.resolve(); },
            waitForState() { return Promise.resolve(state); }
        },
        _bridgeSessionsHandler: {
            sessionObservable: { getState: () => nativeState,
                waitForState: () => Promise.resolve(nativeState) },
            checkLoggedInUser() { counts.nativeCheck++; return Promise.resolve(!!nativeState); }
        },
        _resolveBridgeSession(session) {
            assert.equal(session, state);
            assert.equal(session.bridgeSession, nativeState);
            return Promise.resolve(nativeState);
        }
    });
    handler._logout = handler._logout.bind(handler);
    return { counts, root, handler, bridge, changes, context,
        setNative(value) { nativeState = value; }, state: () => state };
}

test("published session requires native current identity and real validated profile", async () => {
    const h = harness();
    await h.handler.onBridgeSession(h.bridge);
    assert.equal(h.state().bridgeSession, h.bridge);
    assert.equal(h.state().getAccessToken, h.bridge.getAccessToken);
    assert.equal(h.state().transport, h.bridge.transport);
    assert.equal(h.state().isLinked, false);
    assert.equal(h.state().isGuest, false);
    assert.equal(h.state().isStandaloneAuth, true);
    assert.equal(h.handler._latestLinkingError, null);
    assert.equal(h.counts.get + h.counts.link + h.counts.unlink, 0);
});

test("malformed or mismatched authenticated session never publishes", async () => {
    const mutations = [
        h => { h.bridge.userId = "different-user"; },
        h => { h.bridge.getAccessToken = null; },
        h => { h.bridge.transport = null; },
        h => { h.handler.userProfileFetcher.getCurrentUser = () => null; },
        h => { h.handler.userProfileFetcher.getCurrentUserId = () => ""; },
        h => { h.handler.userProfileFetcher.getCurrentUser = () => ({ id: "wrong" }); }
    ];
    for (const mutate of mutations) {
        const h = harness(); mutate(h);
        await assert.rejects(h.handler.onBridgeSession(h.bridge), /lacks authenticated Spotify profile/);
        assert.equal(h.changes.length, 0);
        assert.equal(h.counts.get, 0);
    }
});

test("stale account event cannot replace current frontend session", async () => {
    const h = harness();
    h.setNative({ ...h.bridge });
    await h.handler.onBridgeSession(h.bridge);
    assert.equal(h.changes.length, 0);
});

test("native logged-out state remains logged out and avoids Sony", async () => {
    const h = harness(); h.setNative(null);
    await h.handler.onBridgeSession(null);
    assert.equal(h.state(), null);
    assert.equal(h.counts.nativeCheck, 1);
    assert.equal(h.counts.get, 0);
});

test("real native token/profile error propagates", async () => {
    const h = harness();
    const failure = new Error("Spotify token/profile request failed");
    h.handler._bridgeSessionsHandler.checkLoggedInUser = () => Promise.reject(failure);
    await assert.rejects(h.handler._tryLoginLinkedUser(), e => e === failure);
    assert.equal(h.changes.length, 0);
    assert.equal(h.counts.get, 0);
});

test("normal mode executes original extracted bridge-session method", async () => {
    const h = harness(false);
    await h.handler.onBridgeSession(h.bridge);
    assert.equal(h.counts.get, 1);
    assert.equal(h.state().isStandaloneAuth, undefined);
    assert.equal(h.state().isLinked, false);
});

test("normal mode executes original linked login method and receiver", async () => {
    const h = harness(false);
    let token;
    h.handler._internalLinking.get = function () {
        assert.equal(this, h.handler._internalLinking);
        return Promise.resolve({ spAccessToken: { token: "mock-token" } });
    };
    h.handler._bridgeSessionsHandler.loginAccessToken = value => { token = value; return Promise.resolve(); };
    assert.equal(await h.handler._tryLoginLinkedUser(), true);
    assert.equal(token, "mock-token");
});

test("standalone retry neither opens dialog nor registers another focus retry", async () => {
    const h = harness();
    await h.handler._retryLoginLinkedUserLoop("sony-error");
    h.handler._registerOnFocusListenerOnce();
    assert.equal(h.counts.retry, 0);
    assert.equal(h.counts.focus, 0);
    assert.equal(h.handler._latestLinkingError, null);
    h.root.__spotifyStandaloneAuth = false;
    await h.handler._retryLoginLinkedUserLoop("normal-error");
    h.handler._registerOnFocusListenerOnce();
    assert.equal(h.counts.retry, 1);
    assert.equal(h.counts.focus, 1);
});

test("Sony token/link/unlink entry points blocked only in standalone mode", async () => {
    const h = harness();
    assert.equal(await h.handler._internalLinking.get(), null);
    await assert.rejects(h.handler._internalLinking.link({}), /disabled in standalone/);
    await assert.rejects(h.handler._internalLinking.unlink({}), /disabled in standalone/);
    assert.equal(h.counts.get + h.counts.link + h.counts.unlink, 0);
    h.root.__spotifyStandaloneAuth = false;
    await h.handler._internalLinking.get();
    await h.handler._internalLinking.link({});
    await h.handler._internalLinking.unlink({});
    assert.equal(h.counts.get + h.counts.link + h.counts.unlink, 3);
});

test("actual original logout logs Spotify out without invoking Sony unlink", async () => {
    const h = harness();
    await h.handler.onBridgeSession(h.bridge);
    await h.state().logout();
    assert.equal(h.counts.nativeLogout, 1);
    assert.equal(h.counts.unlink, 0);
});

test("actual patched needsLinking expression preserves ordinary user behavior", () => {
    const start = patched.indexOf("void 0!==n.isLinked&&(l.needsLinking=");
    const expression = patched.slice(start, patched.indexOf(",Ir.kH.getState().updateUser(l)", start));
    for (const [mode, session, expected] of [
        [true, { isLinked: false, isGuest: false, isStandaloneAuth: true, bridgeSession: {} }, false],
        [true, { isLinked: false, isGuest: false }, true],
        [false, { isLinked: false, isGuest: false, isStandaloneAuth: true, bridgeSession: {} }, true],
        [true, { isLinked: false, isGuest: true }, false],
        [true, { isLinked: true, isGuest: false }, false]
    ]) {
        const context = { window: { __spotifyStandaloneAuth: mode }, n: session, l: {} };
        vm.runInNewContext(expression, context);
        assert.equal(context.l.needsLinking, expected);
    }
});

test("actual patched additional-scope expression skips Sony without losing normal mode", async () => {
    const start = patched.indexOf("window.__spotifyStandaloneAuth===true||e.ps5GlobalObject.msdk.connectAccount.setAdditionalScope(");
    const stop = patched.indexOf("}),this.ps5GlobalObject.window.addEventListener", start);
    const expression = patched.slice(start, stop);
    for (const mode of [true, false]) {
        let calls = 0;
        await vm.runInNewContext(expression, { window: { __spotifyStandaloneAuth: mode }, e: {
            ps5GlobalObject: { msdk: { connectAccount: { setAdditionalScope(scope) {
                assert.equal(scope, "psn:app.spotify"); calls++; return Promise.resolve();
            } } } }
        } });
        assert.equal(calls, mode ? 0 : 1);
    }
});

test("actual patched deeplink method accepts only current authenticated standalone session", async () => {
    const start = patched.indexOf("a.getSignedInLinkedUserPromise=") + "a.getSignedInLinkedUserPromise=".length;
    const text = patched.slice(start, patched.indexOf(",a.handleLaunchArgs=", start));
    for (const variant of ["valid", "stale", "unmarked", "linked", "normal-unlinked"]) {
        const h = harness(variant !== "normal-unlinked");
        await h.handler.onBridgeSession(h.bridge);
        let session = h.state();
        if (variant === "unmarked") delete session.isStandaloneAuth;
        if (variant === "stale") h.setNative({ ...h.bridge });
        if (variant === "linked") session.isLinked = true;
        let callback, unsubscribed = 0, settled = false;
        h.handler.sessionObservable.subscribe = fn => { callback = fn; };
        const method = vm.runInContext("(" + text + ")", h.context);
        const promise = method.call({ sessionsHandler: h.handler });
        promise.then(() => { settled = true; });
        callback(session, { unsubscribe() { unsubscribed++; } }, undefined);
        await Promise.resolve();
        const expected = variant === "valid" || variant === "linked";
        assert.equal(settled, expected, variant);
        assert.equal(unsubscribed, expected ? 1 : 0);
    }
});
