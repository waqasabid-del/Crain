(function () {
  const N = document.createElement("link").relList;
  if (N && N.supports && N.supports("modulepreload")) return;
  for (const q of document.querySelectorAll('link[rel="modulepreload"]')) d(q);
  new MutationObserver((q) => {
    for (const V of q)
      if (V.type === "childList")
        for (const vl of V.addedNodes) vl.tagName === "LINK" && vl.rel === "modulepreload" && d(vl);
  }).observe(document, { childList: !0, subtree: !0 });
  function D(q) {
    const V = {};
    return (
      q.integrity && (V.integrity = q.integrity),
      q.referrerPolicy && (V.referrerPolicy = q.referrerPolicy),
      q.crossOrigin === "use-credentials"
        ? (V.credentials = "include")
        : q.crossOrigin === "anonymous"
          ? (V.credentials = "omit")
          : (V.credentials = "same-origin"),
      V
    );
  }
  function d(q) {
    if (q.ep) return;
    q.ep = !0;
    const V = D(q);
    fetch(q.href, V);
  }
})();
var df = { exports: {} },
  pu = {};
var Am;
function oy() {
  if (Am) return pu;
  Am = 1;
  var b = Symbol.for("react.transitional.element"),
    N = Symbol.for("react.fragment");
  function D(d, q, V) {
    var vl = null;
    if ((V !== void 0 && (vl = "" + V), q.key !== void 0 && (vl = "" + q.key), "key" in q)) {
      V = {};
      for (var Nl in q) Nl !== "key" && (V[Nl] = q[Nl]);
    } else V = q;
    return ((q = V.ref), { $$typeof: b, type: d, key: vl, ref: q !== void 0 ? q : null, props: V });
  }
  return ((pu.Fragment = N), (pu.jsx = D), (pu.jsxs = D), pu);
}
var pm;
function my() {
  return (pm || ((pm = 1), (df.exports = oy())), df.exports);
}
var A = my(),
  hf = { exports: {} },
  G = {};
var Om;
function dy() {
  if (Om) return G;
  Om = 1;
  var b = Symbol.for("react.transitional.element"),
    N = Symbol.for("react.portal"),
    D = Symbol.for("react.fragment"),
    d = Symbol.for("react.strict_mode"),
    q = Symbol.for("react.profiler"),
    V = Symbol.for("react.consumer"),
    vl = Symbol.for("react.context"),
    Nl = Symbol.for("react.forward_ref"),
    R = Symbol.for("react.suspense"),
    E = Symbol.for("react.memo"),
    ll = Symbol.for("react.lazy"),
    B = Symbol.for("react.activity"),
    dl = Symbol.iterator;
  function kl(o) {
    return o === null || typeof o != "object"
      ? null
      : ((o = (dl && o[dl]) || o["@@iterator"]), typeof o == "function" ? o : null);
  }
  var Gl = {
      isMounted: function () {
        return !1;
      },
      enqueueForceUpdate: function () {},
      enqueueReplaceState: function () {},
      enqueueSetState: function () {},
    },
    ql = Object.assign,
    Ut = {};
  function Fl(o, T, O) {
    ((this.props = o), (this.context = T), (this.refs = Ut), (this.updater = O || Gl));
  }
  ((Fl.prototype.isReactComponent = {}),
    (Fl.prototype.setState = function (o, T) {
      if (typeof o != "object" && typeof o != "function" && o != null)
        throw Error(
          "takes an object of state variables to update or a function which returns an object of state variables.",
        );
      this.updater.enqueueSetState(this, o, T, "setState");
    }),
    (Fl.prototype.forceUpdate = function (o) {
      this.updater.enqueueForceUpdate(this, o, "forceUpdate");
    }));
  function Ft() {}
  Ft.prototype = Fl.prototype;
  function xl(o, T, O) {
    ((this.props = o), (this.context = T), (this.refs = Ut), (this.updater = O || Gl));
  }
  var ft = (xl.prototype = new Ft());
  ((ft.constructor = xl), ql(ft, Fl.prototype), (ft.isPureReactComponent = !0));
  var Et = Array.isArray;
  function Xl() {}
  var $ = { H: null, A: null, T: null, S: null },
    Ql = Object.prototype.hasOwnProperty;
  function At(o, T, O) {
    var U = O.ref;
    return { $$typeof: b, type: o, key: T, ref: U !== void 0 ? U : null, props: O };
  }
  function wa(o, T) {
    return At(o.type, T, o.props);
  }
  function pt(o) {
    return typeof o == "object" && o !== null && o.$$typeof === b;
  }
  function Zl(o) {
    var T = { "=": "=0", ":": "=2" };
    return (
      "$" +
      o.replace(/[=:]/g, function (O) {
        return T[O];
      })
    );
  }
  var Ea = /\/+/g;
  function Ht(o, T) {
    return typeof o == "object" && o !== null && o.key != null ? Zl("" + o.key) : T.toString(36);
  }
  function bt(o) {
    switch (o.status) {
      case "fulfilled":
        return o.value;
      case "rejected":
        throw o.reason;
      default:
        switch (
          (typeof o.status == "string"
            ? o.then(Xl, Xl)
            : ((o.status = "pending"),
              o.then(
                function (T) {
                  o.status === "pending" && ((o.status = "fulfilled"), (o.value = T));
                },
                function (T) {
                  o.status === "pending" && ((o.status = "rejected"), (o.reason = T));
                },
              )),
          o.status)
        ) {
          case "fulfilled":
            return o.value;
          case "rejected":
            throw o.reason;
        }
    }
    throw o;
  }
  function S(o, T, O, U, X) {
    var L = typeof o;
    (L === "undefined" || L === "boolean") && (o = null);
    var tl = !1;
    if (o === null) tl = !0;
    else
      switch (L) {
        case "bigint":
        case "string":
        case "number":
          tl = !0;
          break;
        case "object":
          switch (o.$$typeof) {
            case b:
            case N:
              tl = !0;
              break;
            case ll:
              return ((tl = o._init), S(tl(o._payload), T, O, U, X));
          }
      }
    if (tl)
      return (
        (X = X(o)),
        (tl = U === "" ? "." + Ht(o, 0) : U),
        Et(X)
          ? ((O = ""),
            tl != null && (O = tl.replace(Ea, "$&/") + "/"),
            S(X, T, O, "", function (je) {
              return je;
            }))
          : X != null &&
            (pt(X) &&
              (X = wa(
                X,
                O +
                  (X.key == null || (o && o.key === X.key)
                    ? ""
                    : ("" + X.key).replace(Ea, "$&/") + "/") +
                  tl,
              )),
            T.push(X)),
        1
      );
    tl = 0;
    var Bl = U === "" ? "." : U + ":";
    if (Et(o))
      for (var Sl = 0; Sl < o.length; Sl++)
        ((U = o[Sl]), (L = Bl + Ht(U, Sl)), (tl += S(U, T, O, L, X)));
    else if (((Sl = kl(o)), typeof Sl == "function"))
      for (o = Sl.call(o), Sl = 0; !(U = o.next()).done;)
        ((U = U.value), (L = Bl + Ht(U, Sl++)), (tl += S(U, T, O, L, X)));
    else if (L === "object") {
      if (typeof o.then == "function") return S(bt(o), T, O, U, X);
      throw (
        (T = String(o)),
        Error(
          "Objects are not valid as a React child (found: " +
            (T === "[object Object]" ? "object with keys {" + Object.keys(o).join(", ") + "}" : T) +
            "). If you meant to render a collection of children, use an array instead.",
        )
      );
    }
    return tl;
  }
  function p(o, T, O) {
    if (o == null) return o;
    var U = [],
      X = 0;
    return (
      S(o, U, "", "", function (L) {
        return T.call(O, L, X++);
      }),
      U
    );
  }
  function Y(o) {
    if (o._status === -1) {
      var T = o._result;
      ((T = T()),
        T.then(
          function (O) {
            (o._status === 0 || o._status === -1) && ((o._status = 1), (o._result = O));
          },
          function (O) {
            (o._status === 0 || o._status === -1) && ((o._status = 2), (o._result = O));
          },
        ),
        o._status === -1 && ((o._status = 0), (o._result = T)));
    }
    if (o._status === 1) return o._result.default;
    throw o._result;
  }
  var ul =
      typeof reportError == "function"
        ? reportError
        : function (o) {
            if (typeof window == "object" && typeof window.ErrorEvent == "function") {
              var T = new window.ErrorEvent("error", {
                bubbles: !0,
                cancelable: !0,
                message:
                  typeof o == "object" && o !== null && typeof o.message == "string"
                    ? String(o.message)
                    : String(o),
                error: o,
              });
              if (!window.dispatchEvent(T)) return;
            } else if (typeof process == "object" && typeof process.emit == "function") {
              process.emit("uncaughtException", o);
              return;
            }
            console.error(o);
          },
    fl = {
      map: p,
      forEach: function (o, T, O) {
        p(
          o,
          function () {
            T.apply(this, arguments);
          },
          O,
        );
      },
      count: function (o) {
        var T = 0;
        return (
          p(o, function () {
            T++;
          }),
          T
        );
      },
      toArray: function (o) {
        return (
          p(o, function (T) {
            return T;
          }) || []
        );
      },
      only: function (o) {
        if (!pt(o))
          throw Error("React.Children.only expected to receive a single React element child.");
        return o;
      },
    };
  return (
    (G.Activity = B),
    (G.Children = fl),
    (G.Component = Fl),
    (G.Fragment = D),
    (G.Profiler = q),
    (G.PureComponent = xl),
    (G.StrictMode = d),
    (G.Suspense = R),
    (G.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE = $),
    (G.__COMPILER_RUNTIME = {
      __proto__: null,
      c: function (o) {
        return $.H.useMemoCache(o);
      },
    }),
    (G.cache = function (o) {
      return function () {
        return o.apply(null, arguments);
      };
    }),
    (G.cacheSignal = function () {
      return null;
    }),
    (G.cloneElement = function (o, T, O) {
      if (o == null) throw Error("The argument must be a React element, but you passed " + o + ".");
      var U = ql({}, o.props),
        X = o.key;
      if (T != null)
        for (L in (T.key !== void 0 && (X = "" + T.key), T))
          !Ql.call(T, L) ||
            L === "key" ||
            L === "__self" ||
            L === "__source" ||
            (L === "ref" && T.ref === void 0) ||
            (U[L] = T[L]);
      var L = arguments.length - 2;
      if (L === 1) U.children = O;
      else if (1 < L) {
        for (var tl = Array(L), Bl = 0; Bl < L; Bl++) tl[Bl] = arguments[Bl + 2];
        U.children = tl;
      }
      return At(o.type, X, U);
    }),
    (G.createContext = function (o) {
      return (
        (o = {
          $$typeof: vl,
          _currentValue: o,
          _currentValue2: o,
          _threadCount: 0,
          Provider: null,
          Consumer: null,
        }),
        (o.Provider = o),
        (o.Consumer = { $$typeof: V, _context: o }),
        o
      );
    }),
    (G.createElement = function (o, T, O) {
      var U,
        X = {},
        L = null;
      if (T != null)
        for (U in (T.key !== void 0 && (L = "" + T.key), T))
          Ql.call(T, U) && U !== "key" && U !== "__self" && U !== "__source" && (X[U] = T[U]);
      var tl = arguments.length - 2;
      if (tl === 1) X.children = O;
      else if (1 < tl) {
        for (var Bl = Array(tl), Sl = 0; Sl < tl; Sl++) Bl[Sl] = arguments[Sl + 2];
        X.children = Bl;
      }
      if (o && o.defaultProps)
        for (U in ((tl = o.defaultProps), tl)) X[U] === void 0 && (X[U] = tl[U]);
      return At(o, L, X);
    }),
    (G.createRef = function () {
      return { current: null };
    }),
    (G.forwardRef = function (o) {
      return { $$typeof: Nl, render: o };
    }),
    (G.isValidElement = pt),
    (G.lazy = function (o) {
      return { $$typeof: ll, _payload: { _status: -1, _result: o }, _init: Y };
    }),
    (G.memo = function (o, T) {
      return { $$typeof: E, type: o, compare: T === void 0 ? null : T };
    }),
    (G.startTransition = function (o) {
      var T = $.T,
        O = {};
      $.T = O;
      try {
        var U = o(),
          X = $.S;
        (X !== null && X(O, U),
          typeof U == "object" && U !== null && typeof U.then == "function" && U.then(Xl, ul));
      } catch (L) {
        ul(L);
      } finally {
        (T !== null && O.types !== null && (T.types = O.types), ($.T = T));
      }
    }),
    (G.unstable_useCacheRefresh = function () {
      return $.H.useCacheRefresh();
    }),
    (G.use = function (o) {
      return $.H.use(o);
    }),
    (G.useActionState = function (o, T, O) {
      return $.H.useActionState(o, T, O);
    }),
    (G.useCallback = function (o, T) {
      return $.H.useCallback(o, T);
    }),
    (G.useContext = function (o) {
      return $.H.useContext(o);
    }),
    (G.useDebugValue = function () {}),
    (G.useDeferredValue = function (o, T) {
      return $.H.useDeferredValue(o, T);
    }),
    (G.useEffect = function (o, T) {
      return $.H.useEffect(o, T);
    }),
    (G.useEffectEvent = function (o) {
      return $.H.useEffectEvent(o);
    }),
    (G.useId = function () {
      return $.H.useId();
    }),
    (G.useImperativeHandle = function (o, T, O) {
      return $.H.useImperativeHandle(o, T, O);
    }),
    (G.useInsertionEffect = function (o, T) {
      return $.H.useInsertionEffect(o, T);
    }),
    (G.useLayoutEffect = function (o, T) {
      return $.H.useLayoutEffect(o, T);
    }),
    (G.useMemo = function (o, T) {
      return $.H.useMemo(o, T);
    }),
    (G.useOptimistic = function (o, T) {
      return $.H.useOptimistic(o, T);
    }),
    (G.useReducer = function (o, T, O) {
      return $.H.useReducer(o, T, O);
    }),
    (G.useRef = function (o) {
      return $.H.useRef(o);
    }),
    (G.useState = function (o) {
      return $.H.useState(o);
    }),
    (G.useSyncExternalStore = function (o, T, O) {
      return $.H.useSyncExternalStore(o, T, O);
    }),
    (G.useTransition = function () {
      return $.H.useTransition();
    }),
    (G.version = "19.2.8"),
    G
  );
}
var Mm;
function _f() {
  return (Mm || ((Mm = 1), (hf.exports = dy())), hf.exports);
}
var zf = _f(),
  yf = { exports: {} },
  Ou = {},
  vf = { exports: {} },
  rf = {};
var Nm;
function hy() {
  return (
    Nm ||
      ((Nm = 1),
      (function (b) {
        function N(S, p) {
          var Y = S.length;
          S.push(p);
          l: for (; 0 < Y;) {
            var ul = (Y - 1) >>> 1,
              fl = S[ul];
            if (0 < q(fl, p)) ((S[ul] = p), (S[Y] = fl), (Y = ul));
            else break l;
          }
        }
        function D(S) {
          return S.length === 0 ? null : S[0];
        }
        function d(S) {
          if (S.length === 0) return null;
          var p = S[0],
            Y = S.pop();
          if (Y !== p) {
            S[0] = Y;
            l: for (var ul = 0, fl = S.length, o = fl >>> 1; ul < o;) {
              var T = 2 * (ul + 1) - 1,
                O = S[T],
                U = T + 1,
                X = S[U];
              if (0 > q(O, Y))
                U < fl && 0 > q(X, O)
                  ? ((S[ul] = X), (S[U] = Y), (ul = U))
                  : ((S[ul] = O), (S[T] = Y), (ul = T));
              else if (U < fl && 0 > q(X, Y)) ((S[ul] = X), (S[U] = Y), (ul = U));
              else break l;
            }
          }
          return p;
        }
        function q(S, p) {
          var Y = S.sortIndex - p.sortIndex;
          return Y !== 0 ? Y : S.id - p.id;
        }
        if (
          ((b.unstable_now = void 0),
          typeof performance == "object" && typeof performance.now == "function")
        ) {
          var V = performance;
          b.unstable_now = function () {
            return V.now();
          };
        } else {
          var vl = Date,
            Nl = vl.now();
          b.unstable_now = function () {
            return vl.now() - Nl;
          };
        }
        var R = [],
          E = [],
          ll = 1,
          B = null,
          dl = 3,
          kl = !1,
          Gl = !1,
          ql = !1,
          Ut = !1,
          Fl = typeof setTimeout == "function" ? setTimeout : null,
          Ft = typeof clearTimeout == "function" ? clearTimeout : null,
          xl = typeof setImmediate < "u" ? setImmediate : null;
        function ft(S) {
          for (var p = D(E); p !== null;) {
            if (p.callback === null) d(E);
            else if (p.startTime <= S) (d(E), (p.sortIndex = p.expirationTime), N(R, p));
            else break;
            p = D(E);
          }
        }
        function Et(S) {
          if (((ql = !1), ft(S), !Gl))
            if (D(R) !== null) ((Gl = !0), Xl || ((Xl = !0), Zl()));
            else {
              var p = D(E);
              p !== null && bt(Et, p.startTime - S);
            }
        }
        var Xl = !1,
          $ = -1,
          Ql = 5,
          At = -1;
        function wa() {
          return Ut ? !0 : !(b.unstable_now() - At < Ql);
        }
        function pt() {
          if (((Ut = !1), Xl)) {
            var S = b.unstable_now();
            At = S;
            var p = !0;
            try {
              l: {
                ((Gl = !1), ql && ((ql = !1), Ft($), ($ = -1)), (kl = !0));
                var Y = dl;
                try {
                  t: {
                    for (ft(S), B = D(R); B !== null && !(B.expirationTime > S && wa());) {
                      var ul = B.callback;
                      if (typeof ul == "function") {
                        ((B.callback = null), (dl = B.priorityLevel));
                        var fl = ul(B.expirationTime <= S);
                        if (((S = b.unstable_now()), typeof fl == "function")) {
                          ((B.callback = fl), ft(S), (p = !0));
                          break t;
                        }
                        (B === D(R) && d(R), ft(S));
                      } else d(R);
                      B = D(R);
                    }
                    if (B !== null) p = !0;
                    else {
                      var o = D(E);
                      (o !== null && bt(Et, o.startTime - S), (p = !1));
                    }
                  }
                  break l;
                } finally {
                  ((B = null), (dl = Y), (kl = !1));
                }
                p = void 0;
              }
            } finally {
              p ? Zl() : (Xl = !1);
            }
          }
        }
        var Zl;
        if (typeof xl == "function")
          Zl = function () {
            xl(pt);
          };
        else if (typeof MessageChannel < "u") {
          var Ea = new MessageChannel(),
            Ht = Ea.port2;
          ((Ea.port1.onmessage = pt),
            (Zl = function () {
              Ht.postMessage(null);
            }));
        } else
          Zl = function () {
            Fl(pt, 0);
          };
        function bt(S, p) {
          $ = Fl(function () {
            S(b.unstable_now());
          }, p);
        }
        ((b.unstable_IdlePriority = 5),
          (b.unstable_ImmediatePriority = 1),
          (b.unstable_LowPriority = 4),
          (b.unstable_NormalPriority = 3),
          (b.unstable_Profiling = null),
          (b.unstable_UserBlockingPriority = 2),
          (b.unstable_cancelCallback = function (S) {
            S.callback = null;
          }),
          (b.unstable_forceFrameRate = function (S) {
            0 > S || 125 < S
              ? console.error(
                  "forceFrameRate takes a positive int between 0 and 125, forcing frame rates higher than 125 fps is not supported",
                )
              : (Ql = 0 < S ? Math.floor(1e3 / S) : 5);
          }),
          (b.unstable_getCurrentPriorityLevel = function () {
            return dl;
          }),
          (b.unstable_next = function (S) {
            switch (dl) {
              case 1:
              case 2:
              case 3:
                var p = 3;
                break;
              default:
                p = dl;
            }
            var Y = dl;
            dl = p;
            try {
              return S();
            } finally {
              dl = Y;
            }
          }),
          (b.unstable_requestPaint = function () {
            Ut = !0;
          }),
          (b.unstable_runWithPriority = function (S, p) {
            switch (S) {
              case 1:
              case 2:
              case 3:
              case 4:
              case 5:
                break;
              default:
                S = 3;
            }
            var Y = dl;
            dl = S;
            try {
              return p();
            } finally {
              dl = Y;
            }
          }),
          (b.unstable_scheduleCallback = function (S, p, Y) {
            var ul = b.unstable_now();
            switch (
              (typeof Y == "object" && Y !== null
                ? ((Y = Y.delay), (Y = typeof Y == "number" && 0 < Y ? ul + Y : ul))
                : (Y = ul),
              S)
            ) {
              case 1:
                var fl = -1;
                break;
              case 2:
                fl = 250;
                break;
              case 5:
                fl = 1073741823;
                break;
              case 4:
                fl = 1e4;
                break;
              default:
                fl = 5e3;
            }
            return (
              (fl = Y + fl),
              (S = {
                id: ll++,
                callback: p,
                priorityLevel: S,
                startTime: Y,
                expirationTime: fl,
                sortIndex: -1,
              }),
              Y > ul
                ? ((S.sortIndex = Y),
                  N(E, S),
                  D(R) === null &&
                    S === D(E) &&
                    (ql ? (Ft($), ($ = -1)) : (ql = !0), bt(Et, Y - ul)))
                : ((S.sortIndex = fl), N(R, S), Gl || kl || ((Gl = !0), Xl || ((Xl = !0), Zl()))),
              S
            );
          }),
          (b.unstable_shouldYield = wa),
          (b.unstable_wrapCallback = function (S) {
            var p = dl;
            return function () {
              var Y = dl;
              dl = p;
              try {
                return S.apply(this, arguments);
              } finally {
                dl = Y;
              }
            };
          }));
      })(rf)),
    rf
  );
}
var Dm;
function yy() {
  return (Dm || ((Dm = 1), (vf.exports = hy())), vf.exports);
}
var gf = { exports: {} },
  Cl = {};
var Um;
function vy() {
  if (Um) return Cl;
  Um = 1;
  var b = _f();
  function N(R) {
    var E = "https://react.dev/errors/" + R;
    if (1 < arguments.length) {
      E += "?args[]=" + encodeURIComponent(arguments[1]);
      for (var ll = 2; ll < arguments.length; ll++)
        E += "&args[]=" + encodeURIComponent(arguments[ll]);
    }
    return (
      "Minified React error #" +
      R +
      "; visit " +
      E +
      " for the full message or use the non-minified dev environment for full errors and additional helpful warnings."
    );
  }
  function D() {}
  var d = {
      d: {
        f: D,
        r: function () {
          throw Error(N(522));
        },
        D,
        C: D,
        L: D,
        m: D,
        X: D,
        S: D,
        M: D,
      },
      p: 0,
      findDOMNode: null,
    },
    q = Symbol.for("react.portal");
  function V(R, E, ll) {
    var B = 3 < arguments.length && arguments[3] !== void 0 ? arguments[3] : null;
    return {
      $$typeof: q,
      key: B == null ? null : "" + B,
      children: R,
      containerInfo: E,
      implementation: ll,
    };
  }
  var vl = b.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
  function Nl(R, E) {
    if (R === "font") return "";
    if (typeof E == "string") return E === "use-credentials" ? E : "";
  }
  return (
    (Cl.__DOM_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE = d),
    (Cl.createPortal = function (R, E) {
      var ll = 2 < arguments.length && arguments[2] !== void 0 ? arguments[2] : null;
      if (!E || (E.nodeType !== 1 && E.nodeType !== 9 && E.nodeType !== 11)) throw Error(N(299));
      return V(R, E, null, ll);
    }),
    (Cl.flushSync = function (R) {
      var E = vl.T,
        ll = d.p;
      try {
        if (((vl.T = null), (d.p = 2), R)) return R();
      } finally {
        ((vl.T = E), (d.p = ll), d.d.f());
      }
    }),
    (Cl.preconnect = function (R, E) {
      typeof R == "string" &&
        (E
          ? ((E = E.crossOrigin),
            (E = typeof E == "string" ? (E === "use-credentials" ? E : "") : void 0))
          : (E = null),
        d.d.C(R, E));
    }),
    (Cl.prefetchDNS = function (R) {
      typeof R == "string" && d.d.D(R);
    }),
    (Cl.preinit = function (R, E) {
      if (typeof R == "string" && E && typeof E.as == "string") {
        var ll = E.as,
          B = Nl(ll, E.crossOrigin),
          dl = typeof E.integrity == "string" ? E.integrity : void 0,
          kl = typeof E.fetchPriority == "string" ? E.fetchPriority : void 0;
        ll === "style"
          ? d.d.S(R, typeof E.precedence == "string" ? E.precedence : void 0, {
              crossOrigin: B,
              integrity: dl,
              fetchPriority: kl,
            })
          : ll === "script" &&
            d.d.X(R, {
              crossOrigin: B,
              integrity: dl,
              fetchPriority: kl,
              nonce: typeof E.nonce == "string" ? E.nonce : void 0,
            });
      }
    }),
    (Cl.preinitModule = function (R, E) {
      if (typeof R == "string")
        if (typeof E == "object" && E !== null) {
          if (E.as == null || E.as === "script") {
            var ll = Nl(E.as, E.crossOrigin);
            d.d.M(R, {
              crossOrigin: ll,
              integrity: typeof E.integrity == "string" ? E.integrity : void 0,
              nonce: typeof E.nonce == "string" ? E.nonce : void 0,
            });
          }
        } else E == null && d.d.M(R);
    }),
    (Cl.preload = function (R, E) {
      if (typeof R == "string" && typeof E == "object" && E !== null && typeof E.as == "string") {
        var ll = E.as,
          B = Nl(ll, E.crossOrigin);
        d.d.L(R, ll, {
          crossOrigin: B,
          integrity: typeof E.integrity == "string" ? E.integrity : void 0,
          nonce: typeof E.nonce == "string" ? E.nonce : void 0,
          type: typeof E.type == "string" ? E.type : void 0,
          fetchPriority: typeof E.fetchPriority == "string" ? E.fetchPriority : void 0,
          referrerPolicy: typeof E.referrerPolicy == "string" ? E.referrerPolicy : void 0,
          imageSrcSet: typeof E.imageSrcSet == "string" ? E.imageSrcSet : void 0,
          imageSizes: typeof E.imageSizes == "string" ? E.imageSizes : void 0,
          media: typeof E.media == "string" ? E.media : void 0,
        });
      }
    }),
    (Cl.preloadModule = function (R, E) {
      if (typeof R == "string")
        if (E) {
          var ll = Nl(E.as, E.crossOrigin);
          d.d.m(R, {
            as: typeof E.as == "string" && E.as !== "script" ? E.as : void 0,
            crossOrigin: ll,
            integrity: typeof E.integrity == "string" ? E.integrity : void 0,
          });
        } else d.d.m(R);
    }),
    (Cl.requestFormReset = function (R) {
      d.d.r(R);
    }),
    (Cl.unstable_batchedUpdates = function (R, E) {
      return R(E);
    }),
    (Cl.useFormState = function (R, E, ll) {
      return vl.H.useFormState(R, E, ll);
    }),
    (Cl.useFormStatus = function () {
      return vl.H.useHostTransitionStatus();
    }),
    (Cl.version = "19.2.8"),
    Cl
  );
}
var Hm;
function ry() {
  if (Hm) return gf.exports;
  Hm = 1;
  function b() {
    if (!(
      typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ > "u" ||
      typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE != "function"
    ))
      try {
        __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(b);
      } catch (N) {
        console.error(N);
      }
  }
  return (b(), (gf.exports = vy()), gf.exports);
}
var jm;
function gy() {
  if (jm) return Ou;
  jm = 1;
  var b = yy(),
    N = _f(),
    D = ry();
  function d(l) {
    var t = "https://react.dev/errors/" + l;
    if (1 < arguments.length) {
      t += "?args[]=" + encodeURIComponent(arguments[1]);
      for (var a = 2; a < arguments.length; a++) t += "&args[]=" + encodeURIComponent(arguments[a]);
    }
    return (
      "Minified React error #" +
      l +
      "; visit " +
      t +
      " for the full message or use the non-minified dev environment for full errors and additional helpful warnings."
    );
  }
  function q(l) {
    return !(!l || (l.nodeType !== 1 && l.nodeType !== 9 && l.nodeType !== 11));
  }
  function V(l) {
    var t = l,
      a = l;
    if (l.alternate) for (; t.return;) t = t.return;
    else {
      l = t;
      do ((t = l), (t.flags & 4098) !== 0 && (a = t.return), (l = t.return));
      while (l);
    }
    return t.tag === 3 ? a : null;
  }
  function vl(l) {
    if (l.tag === 13) {
      var t = l.memoizedState;
      if ((t === null && ((l = l.alternate), l !== null && (t = l.memoizedState)), t !== null))
        return t.dehydrated;
    }
    return null;
  }
  function Nl(l) {
    if (l.tag === 31) {
      var t = l.memoizedState;
      if ((t === null && ((l = l.alternate), l !== null && (t = l.memoizedState)), t !== null))
        return t.dehydrated;
    }
    return null;
  }
  function R(l) {
    if (V(l) !== l) throw Error(d(188));
  }
  function E(l) {
    var t = l.alternate;
    if (!t) {
      if (((t = V(l)), t === null)) throw Error(d(188));
      return t !== l ? null : l;
    }
    for (var a = l, e = t; ;) {
      var u = a.return;
      if (u === null) break;
      var n = u.alternate;
      if (n === null) {
        if (((e = u.return), e !== null)) {
          a = e;
          continue;
        }
        break;
      }
      if (u.child === n.child) {
        for (n = u.child; n;) {
          if (n === a) return (R(u), l);
          if (n === e) return (R(u), t);
          n = n.sibling;
        }
        throw Error(d(188));
      }
      if (a.return !== e.return) ((a = u), (e = n));
      else {
        for (var i = !1, c = u.child; c;) {
          if (c === a) {
            ((i = !0), (a = u), (e = n));
            break;
          }
          if (c === e) {
            ((i = !0), (e = u), (a = n));
            break;
          }
          c = c.sibling;
        }
        if (!i) {
          for (c = n.child; c;) {
            if (c === a) {
              ((i = !0), (a = n), (e = u));
              break;
            }
            if (c === e) {
              ((i = !0), (e = n), (a = u));
              break;
            }
            c = c.sibling;
          }
          if (!i) throw Error(d(189));
        }
      }
      if (a.alternate !== e) throw Error(d(190));
    }
    if (a.tag !== 3) throw Error(d(188));
    return a.stateNode.current === a ? l : t;
  }
  function ll(l) {
    var t = l.tag;
    if (t === 5 || t === 26 || t === 27 || t === 6) return l;
    for (l = l.child; l !== null;) {
      if (((t = ll(l)), t !== null)) return t;
      l = l.sibling;
    }
    return null;
  }
  var B = Object.assign,
    dl = Symbol.for("react.element"),
    kl = Symbol.for("react.transitional.element"),
    Gl = Symbol.for("react.portal"),
    ql = Symbol.for("react.fragment"),
    Ut = Symbol.for("react.strict_mode"),
    Fl = Symbol.for("react.profiler"),
    Ft = Symbol.for("react.consumer"),
    xl = Symbol.for("react.context"),
    ft = Symbol.for("react.forward_ref"),
    Et = Symbol.for("react.suspense"),
    Xl = Symbol.for("react.suspense_list"),
    $ = Symbol.for("react.memo"),
    Ql = Symbol.for("react.lazy"),
    At = Symbol.for("react.activity"),
    wa = Symbol.for("react.memo_cache_sentinel"),
    pt = Symbol.iterator;
  function Zl(l) {
    return l === null || typeof l != "object"
      ? null
      : ((l = (pt && l[pt]) || l["@@iterator"]), typeof l == "function" ? l : null);
  }
  var Ea = Symbol.for("react.client.reference");
  function Ht(l) {
    if (l == null) return null;
    if (typeof l == "function") return l.$$typeof === Ea ? null : l.displayName || l.name || null;
    if (typeof l == "string") return l;
    switch (l) {
      case ql:
        return "Fragment";
      case Fl:
        return "Profiler";
      case Ut:
        return "StrictMode";
      case Et:
        return "Suspense";
      case Xl:
        return "SuspenseList";
      case At:
        return "Activity";
    }
    if (typeof l == "object")
      switch (l.$$typeof) {
        case Gl:
          return "Portal";
        case xl:
          return l.displayName || "Context";
        case Ft:
          return (l._context.displayName || "Context") + ".Consumer";
        case ft:
          var t = l.render;
          return (
            (l = l.displayName),
            l ||
              ((l = t.displayName || t.name || ""),
              (l = l !== "" ? "ForwardRef(" + l + ")" : "ForwardRef")),
            l
          );
        case $:
          return ((t = l.displayName || null), t !== null ? t : Ht(l.type) || "Memo");
        case Ql:
          ((t = l._payload), (l = l._init));
          try {
            return Ht(l(t));
          } catch {}
      }
    return null;
  }
  var bt = Array.isArray,
    S = N.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE,
    p = D.__DOM_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE,
    Y = { pending: !1, data: null, method: null, action: null },
    ul = [],
    fl = -1;
  function o(l) {
    return { current: l };
  }
  function T(l) {
    0 > fl || ((l.current = ul[fl]), (ul[fl] = null), fl--);
  }
  function O(l, t) {
    (fl++, (ul[fl] = l.current), (l.current = t));
  }
  var U = o(null),
    X = o(null),
    L = o(null),
    tl = o(null);
  function Bl(l, t) {
    switch ((O(L, t), O(X, l), O(U, null), t.nodeType)) {
      case 9:
      case 11:
        l = (l = t.documentElement) && (l = l.namespaceURI) ? w0(l) : 0;
        break;
      default:
        if (((l = t.tagName), (t = t.namespaceURI))) ((t = w0(t)), (l = W0(t, l)));
        else
          switch (l) {
            case "svg":
              l = 1;
              break;
            case "math":
              l = 2;
              break;
            default:
              l = 0;
          }
    }
    (T(U), O(U, l));
  }
  function Sl() {
    (T(U), T(X), T(L));
  }
  function je(l) {
    l.memoizedState !== null && O(tl, l);
    var t = U.current,
      a = W0(t, l.type);
    t !== a && (O(X, l), O(U, a));
  }
  function Mu(l) {
    (X.current === l && (T(U), T(X)), tl.current === l && (T(tl), (_u._currentValue = Y)));
  }
  var wn, Tf;
  function Aa(l) {
    if (wn === void 0)
      try {
        throw Error();
      } catch (a) {
        var t = a.stack.trim().match(/\n( *(at )?)/);
        ((wn = (t && t[1]) || ""),
          (Tf =
            -1 <
            a.stack.indexOf(`
    at`)
              ? " (<anonymous>)"
              : -1 < a.stack.indexOf("@")
                ? "@unknown:0:0"
                : ""));
      }
    return (
      `
` +
      wn +
      l +
      Tf
    );
  }
  var Wn = !1;
  function $n(l, t) {
    if (!l || Wn) return "";
    Wn = !0;
    var a = Error.prepareStackTrace;
    Error.prepareStackTrace = void 0;
    try {
      var e = {
        DetermineComponentFrameRoot: function () {
          try {
            if (t) {
              var _ = function () {
                throw Error();
              };
              if (
                (Object.defineProperty(_.prototype, "props", {
                  set: function () {
                    throw Error();
                  },
                }),
                typeof Reflect == "object" && Reflect.construct)
              ) {
                try {
                  Reflect.construct(_, []);
                } catch (r) {
                  var v = r;
                }
                Reflect.construct(l, [], _);
              } else {
                try {
                  _.call();
                } catch (r) {
                  v = r;
                }
                l.call(_.prototype);
              }
            } else {
              try {
                throw Error();
              } catch (r) {
                v = r;
              }
              (_ = l()) && typeof _.catch == "function" && _.catch(function () {});
            }
          } catch (r) {
            if (r && v && typeof r.stack == "string") return [r.stack, v.stack];
          }
          return [null, null];
        },
      };
      e.DetermineComponentFrameRoot.displayName = "DetermineComponentFrameRoot";
      var u = Object.getOwnPropertyDescriptor(e.DetermineComponentFrameRoot, "name");
      u &&
        u.configurable &&
        Object.defineProperty(e.DetermineComponentFrameRoot, "name", {
          value: "DetermineComponentFrameRoot",
        });
      var n = e.DetermineComponentFrameRoot(),
        i = n[0],
        c = n[1];
      if (i && c) {
        var f = i.split(`
`),
          y = c.split(`
`);
        for (u = e = 0; e < f.length && !f[e].includes("DetermineComponentFrameRoot");) e++;
        for (; u < y.length && !y[u].includes("DetermineComponentFrameRoot");) u++;
        if (e === f.length || u === y.length)
          for (e = f.length - 1, u = y.length - 1; 1 <= e && 0 <= u && f[e] !== y[u];) u--;
        for (; 1 <= e && 0 <= u; e--, u--)
          if (f[e] !== y[u]) {
            if (e !== 1 || u !== 1)
              do
                if ((e--, u--, 0 > u || f[e] !== y[u])) {
                  var g =
                    `
` + f[e].replace(" at new ", " at ");
                  return (
                    l.displayName &&
                      g.includes("<anonymous>") &&
                      (g = g.replace("<anonymous>", l.displayName)),
                    g
                  );
                }
              while (1 <= e && 0 <= u);
            break;
          }
      }
    } finally {
      ((Wn = !1), (Error.prepareStackTrace = a));
    }
    return (a = l ? l.displayName || l.name : "") ? Aa(a) : "";
  }
  function Qm(l, t) {
    switch (l.tag) {
      case 26:
      case 27:
      case 5:
        return Aa(l.type);
      case 16:
        return Aa("Lazy");
      case 13:
        return l.child !== t && t !== null ? Aa("Suspense Fallback") : Aa("Suspense");
      case 19:
        return Aa("SuspenseList");
      case 0:
      case 15:
        return $n(l.type, !1);
      case 11:
        return $n(l.type.render, !1);
      case 1:
        return $n(l.type, !0);
      case 31:
        return Aa("Activity");
      default:
        return "";
    }
  }
  function Ef(l) {
    try {
      var t = "",
        a = null;
      do ((t += Qm(l, a)), (a = l), (l = l.return));
      while (l);
      return t;
    } catch (e) {
      return (
        `
Error generating stack: ` +
        e.message +
        `
` +
        e.stack
      );
    }
  }
  var kn = Object.prototype.hasOwnProperty,
    Fn = b.unstable_scheduleCallback,
    In = b.unstable_cancelCallback,
    Zm = b.unstable_shouldYield,
    Vm = b.unstable_requestPaint,
    Il = b.unstable_now,
    Lm = b.unstable_getCurrentPriorityLevel,
    Af = b.unstable_ImmediatePriority,
    pf = b.unstable_UserBlockingPriority,
    Nu = b.unstable_NormalPriority,
    Km = b.unstable_LowPriority,
    Of = b.unstable_IdlePriority,
    Jm = b.log,
    wm = b.unstable_setDisableYieldValue,
    Re = null,
    Pl = null;
  function It(l) {
    if ((typeof Jm == "function" && wm(l), Pl && typeof Pl.setStrictMode == "function"))
      try {
        Pl.setStrictMode(Re, l);
      } catch {}
  }
  var lt = Math.clz32 ? Math.clz32 : km,
    Wm = Math.log,
    $m = Math.LN2;
  function km(l) {
    return ((l >>>= 0), l === 0 ? 32 : (31 - ((Wm(l) / $m) | 0)) | 0);
  }
  var Du = 256,
    Uu = 262144,
    Hu = 4194304;
  function pa(l) {
    var t = l & 42;
    if (t !== 0) return t;
    switch (l & -l) {
      case 1:
        return 1;
      case 2:
        return 2;
      case 4:
        return 4;
      case 8:
        return 8;
      case 16:
        return 16;
      case 32:
        return 32;
      case 64:
        return 64;
      case 128:
        return 128;
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
        return l & 261888;
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
        return l & 3932160;
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        return l & 62914560;
      case 67108864:
        return 67108864;
      case 134217728:
        return 134217728;
      case 268435456:
        return 268435456;
      case 536870912:
        return 536870912;
      case 1073741824:
        return 0;
      default:
        return l;
    }
  }
  function ju(l, t, a) {
    var e = l.pendingLanes;
    if (e === 0) return 0;
    var u = 0,
      n = l.suspendedLanes,
      i = l.pingedLanes;
    l = l.warmLanes;
    var c = e & 134217727;
    return (
      c !== 0
        ? ((e = c & ~n),
          e !== 0
            ? (u = pa(e))
            : ((i &= c), i !== 0 ? (u = pa(i)) : a || ((a = c & ~l), a !== 0 && (u = pa(a)))))
        : ((c = e & ~n),
          c !== 0
            ? (u = pa(c))
            : i !== 0
              ? (u = pa(i))
              : a || ((a = e & ~l), a !== 0 && (u = pa(a)))),
      u === 0
        ? 0
        : t !== 0 &&
            t !== u &&
            (t & n) === 0 &&
            ((n = u & -u), (a = t & -t), n >= a || (n === 32 && (a & 4194048) !== 0))
          ? t
          : u
    );
  }
  function xe(l, t) {
    return (l.pendingLanes & ~(l.suspendedLanes & ~l.pingedLanes) & t) === 0;
  }
  function Fm(l, t) {
    switch (l) {
      case 1:
      case 2:
      case 4:
      case 8:
      case 64:
        return t + 250;
      case 16:
      case 32:
      case 128:
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
        return t + 5e3;
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        return -1;
      case 67108864:
      case 134217728:
      case 268435456:
      case 536870912:
      case 1073741824:
        return -1;
      default:
        return -1;
    }
  }
  function Mf() {
    var l = Hu;
    return ((Hu <<= 1), (Hu & 62914560) === 0 && (Hu = 4194304), l);
  }
  function Pn(l) {
    for (var t = [], a = 0; 31 > a; a++) t.push(l);
    return t;
  }
  function Ce(l, t) {
    ((l.pendingLanes |= t),
      t !== 268435456 && ((l.suspendedLanes = 0), (l.pingedLanes = 0), (l.warmLanes = 0)));
  }
  function Im(l, t, a, e, u, n) {
    var i = l.pendingLanes;
    ((l.pendingLanes = a),
      (l.suspendedLanes = 0),
      (l.pingedLanes = 0),
      (l.warmLanes = 0),
      (l.expiredLanes &= a),
      (l.entangledLanes &= a),
      (l.errorRecoveryDisabledLanes &= a),
      (l.shellSuspendCounter = 0));
    var c = l.entanglements,
      f = l.expirationTimes,
      y = l.hiddenUpdates;
    for (a = i & ~a; 0 < a;) {
      var g = 31 - lt(a),
        _ = 1 << g;
      ((c[g] = 0), (f[g] = -1));
      var v = y[g];
      if (v !== null)
        for (y[g] = null, g = 0; g < v.length; g++) {
          var r = v[g];
          r !== null && (r.lane &= -536870913);
        }
      a &= ~_;
    }
    (e !== 0 && Nf(l, e, 0),
      n !== 0 && u === 0 && l.tag !== 0 && (l.suspendedLanes |= n & ~(i & ~t)));
  }
  function Nf(l, t, a) {
    ((l.pendingLanes |= t), (l.suspendedLanes &= ~t));
    var e = 31 - lt(t);
    ((l.entangledLanes |= t),
      (l.entanglements[e] = l.entanglements[e] | 1073741824 | (a & 261930)));
  }
  function Df(l, t) {
    var a = (l.entangledLanes |= t);
    for (l = l.entanglements; a;) {
      var e = 31 - lt(a),
        u = 1 << e;
      ((u & t) | (l[e] & t) && (l[e] |= t), (a &= ~u));
    }
  }
  function Uf(l, t) {
    var a = t & -t;
    return ((a = (a & 42) !== 0 ? 1 : li(a)), (a & (l.suspendedLanes | t)) !== 0 ? 0 : a);
  }
  function li(l) {
    switch (l) {
      case 2:
        l = 1;
        break;
      case 8:
        l = 4;
        break;
      case 32:
        l = 16;
        break;
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        l = 128;
        break;
      case 268435456:
        l = 134217728;
        break;
      default:
        l = 0;
    }
    return l;
  }
  function ti(l) {
    return ((l &= -l), 2 < l ? (8 < l ? ((l & 134217727) !== 0 ? 32 : 268435456) : 8) : 2);
  }
  function Hf() {
    var l = p.p;
    return l !== 0 ? l : ((l = window.event), l === void 0 ? 32 : gm(l.type));
  }
  function jf(l, t) {
    var a = p.p;
    try {
      return ((p.p = l), t());
    } finally {
      p.p = a;
    }
  }
  var Pt = Math.random().toString(36).slice(2),
    Dl = "__reactFiber$" + Pt,
    Vl = "__reactProps$" + Pt,
    Wa = "__reactContainer$" + Pt,
    ai = "__reactEvents$" + Pt,
    Pm = "__reactListeners$" + Pt,
    ld = "__reactHandles$" + Pt,
    Rf = "__reactResources$" + Pt,
    qe = "__reactMarker$" + Pt;
  function ei(l) {
    (delete l[Dl], delete l[Vl], delete l[ai], delete l[Pm], delete l[ld]);
  }
  function $a(l) {
    var t = l[Dl];
    if (t) return t;
    for (var a = l.parentNode; a;) {
      if ((t = a[Wa] || a[Dl])) {
        if (((a = t.alternate), t.child !== null || (a !== null && a.child !== null)))
          for (l = tm(l); l !== null;) {
            if ((a = l[Dl])) return a;
            l = tm(l);
          }
        return t;
      }
      ((l = a), (a = l.parentNode));
    }
    return null;
  }
  function ka(l) {
    if ((l = l[Dl] || l[Wa])) {
      var t = l.tag;
      if (t === 5 || t === 6 || t === 13 || t === 31 || t === 26 || t === 27 || t === 3) return l;
    }
    return null;
  }
  function Be(l) {
    var t = l.tag;
    if (t === 5 || t === 26 || t === 27 || t === 6) return l.stateNode;
    throw Error(d(33));
  }
  function Fa(l) {
    var t = l[Rf];
    return (t || (t = l[Rf] = { hoistableStyles: new Map(), hoistableScripts: new Map() }), t);
  }
  function Ol(l) {
    l[qe] = !0;
  }
  var xf = new Set(),
    Cf = {};
  function Oa(l, t) {
    (Ia(l, t), Ia(l + "Capture", t));
  }
  function Ia(l, t) {
    for (Cf[l] = t, l = 0; l < t.length; l++) xf.add(t[l]);
  }
  var td = RegExp(
      "^[:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD][:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD\\-.0-9\\u00B7\\u0300-\\u036F\\u203F-\\u2040]*$",
    ),
    qf = {},
    Bf = {};
  function ad(l) {
    return kn.call(Bf, l)
      ? !0
      : kn.call(qf, l)
        ? !1
        : td.test(l)
          ? (Bf[l] = !0)
          : ((qf[l] = !0), !1);
  }
  function Ru(l, t, a) {
    if (ad(t))
      if (a === null) l.removeAttribute(t);
      else {
        switch (typeof a) {
          case "undefined":
          case "function":
          case "symbol":
            l.removeAttribute(t);
            return;
          case "boolean":
            var e = t.toLowerCase().slice(0, 5);
            if (e !== "data-" && e !== "aria-") {
              l.removeAttribute(t);
              return;
            }
        }
        l.setAttribute(t, "" + a);
      }
  }
  function xu(l, t, a) {
    if (a === null) l.removeAttribute(t);
    else {
      switch (typeof a) {
        case "undefined":
        case "function":
        case "symbol":
        case "boolean":
          l.removeAttribute(t);
          return;
      }
      l.setAttribute(t, "" + a);
    }
  }
  function jt(l, t, a, e) {
    if (e === null) l.removeAttribute(a);
    else {
      switch (typeof e) {
        case "undefined":
        case "function":
        case "symbol":
        case "boolean":
          l.removeAttribute(a);
          return;
      }
      l.setAttributeNS(t, a, "" + e);
    }
  }
  function st(l) {
    switch (typeof l) {
      case "bigint":
      case "boolean":
      case "number":
      case "string":
      case "undefined":
        return l;
      case "object":
        return l;
      default:
        return "";
    }
  }
  function Yf(l) {
    var t = l.type;
    return (l = l.nodeName) && l.toLowerCase() === "input" && (t === "checkbox" || t === "radio");
  }
  function ed(l, t, a) {
    var e = Object.getOwnPropertyDescriptor(l.constructor.prototype, t);
    if (
      !l.hasOwnProperty(t) &&
      typeof e < "u" &&
      typeof e.get == "function" &&
      typeof e.set == "function"
    ) {
      var u = e.get,
        n = e.set;
      return (
        Object.defineProperty(l, t, {
          configurable: !0,
          get: function () {
            return u.call(this);
          },
          set: function (i) {
            ((a = "" + i), n.call(this, i));
          },
        }),
        Object.defineProperty(l, t, { enumerable: e.enumerable }),
        {
          getValue: function () {
            return a;
          },
          setValue: function (i) {
            a = "" + i;
          },
          stopTracking: function () {
            ((l._valueTracker = null), delete l[t]);
          },
        }
      );
    }
  }
  function ui(l) {
    if (!l._valueTracker) {
      var t = Yf(l) ? "checked" : "value";
      l._valueTracker = ed(l, t, "" + l[t]);
    }
  }
  function Gf(l) {
    if (!l) return !1;
    var t = l._valueTracker;
    if (!t) return !0;
    var a = t.getValue(),
      e = "";
    return (
      l && (e = Yf(l) ? (l.checked ? "true" : "false") : l.value),
      (l = e),
      l !== a ? (t.setValue(l), !0) : !1
    );
  }
  function Cu(l) {
    if (((l = l || (typeof document < "u" ? document : void 0)), typeof l > "u")) return null;
    try {
      return l.activeElement || l.body;
    } catch {
      return l.body;
    }
  }
  var ud = /[\n"\\]/g;
  function ot(l) {
    return l.replace(ud, function (t) {
      return "\\" + t.charCodeAt(0).toString(16) + " ";
    });
  }
  function ni(l, t, a, e, u, n, i, c) {
    ((l.name = ""),
      i != null && typeof i != "function" && typeof i != "symbol" && typeof i != "boolean"
        ? (l.type = i)
        : l.removeAttribute("type"),
      t != null
        ? i === "number"
          ? ((t === 0 && l.value === "") || l.value != t) && (l.value = "" + st(t))
          : l.value !== "" + st(t) && (l.value = "" + st(t))
        : (i !== "submit" && i !== "reset") || l.removeAttribute("value"),
      t != null
        ? ii(l, i, st(t))
        : a != null
          ? ii(l, i, st(a))
          : e != null && l.removeAttribute("value"),
      u == null && n != null && (l.defaultChecked = !!n),
      u != null && (l.checked = u && typeof u != "function" && typeof u != "symbol"),
      c != null && typeof c != "function" && typeof c != "symbol" && typeof c != "boolean"
        ? (l.name = "" + st(c))
        : l.removeAttribute("name"));
  }
  function Xf(l, t, a, e, u, n, i, c) {
    if (
      (n != null &&
        typeof n != "function" &&
        typeof n != "symbol" &&
        typeof n != "boolean" &&
        (l.type = n),
      t != null || a != null)
    ) {
      if (!((n !== "submit" && n !== "reset") || t != null)) {
        ui(l);
        return;
      }
      ((a = a != null ? "" + st(a) : ""),
        (t = t != null ? "" + st(t) : a),
        c || t === l.value || (l.value = t),
        (l.defaultValue = t));
    }
    ((e = e ?? u),
      (e = typeof e != "function" && typeof e != "symbol" && !!e),
      (l.checked = c ? l.checked : !!e),
      (l.defaultChecked = !!e),
      i != null &&
        typeof i != "function" &&
        typeof i != "symbol" &&
        typeof i != "boolean" &&
        (l.name = i),
      ui(l));
  }
  function ii(l, t, a) {
    (t === "number" && Cu(l.ownerDocument) === l) ||
      l.defaultValue === "" + a ||
      (l.defaultValue = "" + a);
  }
  function Pa(l, t, a, e) {
    if (((l = l.options), t)) {
      t = {};
      for (var u = 0; u < a.length; u++) t["$" + a[u]] = !0;
      for (a = 0; a < l.length; a++)
        ((u = t.hasOwnProperty("$" + l[a].value)),
          l[a].selected !== u && (l[a].selected = u),
          u && e && (l[a].defaultSelected = !0));
    } else {
      for (a = "" + st(a), t = null, u = 0; u < l.length; u++) {
        if (l[u].value === a) {
          ((l[u].selected = !0), e && (l[u].defaultSelected = !0));
          return;
        }
        t !== null || l[u].disabled || (t = l[u]);
      }
      t !== null && (t.selected = !0);
    }
  }
  function Qf(l, t, a) {
    if (t != null && ((t = "" + st(t)), t !== l.value && (l.value = t), a == null)) {
      l.defaultValue !== t && (l.defaultValue = t);
      return;
    }
    l.defaultValue = a != null ? "" + st(a) : "";
  }
  function Zf(l, t, a, e) {
    if (t == null) {
      if (e != null) {
        if (a != null) throw Error(d(92));
        if (bt(e)) {
          if (1 < e.length) throw Error(d(93));
          e = e[0];
        }
        a = e;
      }
      (a == null && (a = ""), (t = a));
    }
    ((a = st(t)),
      (l.defaultValue = a),
      (e = l.textContent),
      e === a && e !== "" && e !== null && (l.value = e),
      ui(l));
  }
  function le(l, t) {
    if (t) {
      var a = l.firstChild;
      if (a && a === l.lastChild && a.nodeType === 3) {
        a.nodeValue = t;
        return;
      }
    }
    l.textContent = t;
  }
  var nd = new Set(
    "animationIterationCount aspectRatio borderImageOutset borderImageSlice borderImageWidth boxFlex boxFlexGroup boxOrdinalGroup columnCount columns flex flexGrow flexPositive flexShrink flexNegative flexOrder gridArea gridRow gridRowEnd gridRowSpan gridRowStart gridColumn gridColumnEnd gridColumnSpan gridColumnStart fontWeight lineClamp lineHeight opacity order orphans scale tabSize widows zIndex zoom fillOpacity floodOpacity stopOpacity strokeDasharray strokeDashoffset strokeMiterlimit strokeOpacity strokeWidth MozAnimationIterationCount MozBoxFlex MozBoxFlexGroup MozLineClamp msAnimationIterationCount msFlex msZoom msFlexGrow msFlexNegative msFlexOrder msFlexPositive msFlexShrink msGridColumn msGridColumnSpan msGridRow msGridRowSpan WebkitAnimationIterationCount WebkitBoxFlex WebKitBoxFlexGroup WebkitBoxOrdinalGroup WebkitColumnCount WebkitColumns WebkitFlex WebkitFlexGrow WebkitFlexPositive WebkitFlexShrink WebkitLineClamp".split(
      " ",
    ),
  );
  function Vf(l, t, a) {
    var e = t.indexOf("--") === 0;
    a == null || typeof a == "boolean" || a === ""
      ? e
        ? l.setProperty(t, "")
        : t === "float"
          ? (l.cssFloat = "")
          : (l[t] = "")
      : e
        ? l.setProperty(t, a)
        : typeof a != "number" || a === 0 || nd.has(t)
          ? t === "float"
            ? (l.cssFloat = a)
            : (l[t] = ("" + a).trim())
          : (l[t] = a + "px");
  }
  function Lf(l, t, a) {
    if (t != null && typeof t != "object") throw Error(d(62));
    if (((l = l.style), a != null)) {
      for (var e in a)
        !a.hasOwnProperty(e) ||
          (t != null && t.hasOwnProperty(e)) ||
          (e.indexOf("--") === 0
            ? l.setProperty(e, "")
            : e === "float"
              ? (l.cssFloat = "")
              : (l[e] = ""));
      for (var u in t) ((e = t[u]), t.hasOwnProperty(u) && a[u] !== e && Vf(l, u, e));
    } else for (var n in t) t.hasOwnProperty(n) && Vf(l, n, t[n]);
  }
  function ci(l) {
    if (l.indexOf("-") === -1) return !1;
    switch (l) {
      case "annotation-xml":
      case "color-profile":
      case "font-face":
      case "font-face-src":
      case "font-face-uri":
      case "font-face-format":
      case "font-face-name":
      case "missing-glyph":
        return !1;
      default:
        return !0;
    }
  }
  var id = new Map([
      ["acceptCharset", "accept-charset"],
      ["htmlFor", "for"],
      ["httpEquiv", "http-equiv"],
      ["crossOrigin", "crossorigin"],
      ["accentHeight", "accent-height"],
      ["alignmentBaseline", "alignment-baseline"],
      ["arabicForm", "arabic-form"],
      ["baselineShift", "baseline-shift"],
      ["capHeight", "cap-height"],
      ["clipPath", "clip-path"],
      ["clipRule", "clip-rule"],
      ["colorInterpolation", "color-interpolation"],
      ["colorInterpolationFilters", "color-interpolation-filters"],
      ["colorProfile", "color-profile"],
      ["colorRendering", "color-rendering"],
      ["dominantBaseline", "dominant-baseline"],
      ["enableBackground", "enable-background"],
      ["fillOpacity", "fill-opacity"],
      ["fillRule", "fill-rule"],
      ["floodColor", "flood-color"],
      ["floodOpacity", "flood-opacity"],
      ["fontFamily", "font-family"],
      ["fontSize", "font-size"],
      ["fontSizeAdjust", "font-size-adjust"],
      ["fontStretch", "font-stretch"],
      ["fontStyle", "font-style"],
      ["fontVariant", "font-variant"],
      ["fontWeight", "font-weight"],
      ["glyphName", "glyph-name"],
      ["glyphOrientationHorizontal", "glyph-orientation-horizontal"],
      ["glyphOrientationVertical", "glyph-orientation-vertical"],
      ["horizAdvX", "horiz-adv-x"],
      ["horizOriginX", "horiz-origin-x"],
      ["imageRendering", "image-rendering"],
      ["letterSpacing", "letter-spacing"],
      ["lightingColor", "lighting-color"],
      ["markerEnd", "marker-end"],
      ["markerMid", "marker-mid"],
      ["markerStart", "marker-start"],
      ["overlinePosition", "overline-position"],
      ["overlineThickness", "overline-thickness"],
      ["paintOrder", "paint-order"],
      ["panose-1", "panose-1"],
      ["pointerEvents", "pointer-events"],
      ["renderingIntent", "rendering-intent"],
      ["shapeRendering", "shape-rendering"],
      ["stopColor", "stop-color"],
      ["stopOpacity", "stop-opacity"],
      ["strikethroughPosition", "strikethrough-position"],
      ["strikethroughThickness", "strikethrough-thickness"],
      ["strokeDasharray", "stroke-dasharray"],
      ["strokeDashoffset", "stroke-dashoffset"],
      ["strokeLinecap", "stroke-linecap"],
      ["strokeLinejoin", "stroke-linejoin"],
      ["strokeMiterlimit", "stroke-miterlimit"],
      ["strokeOpacity", "stroke-opacity"],
      ["strokeWidth", "stroke-width"],
      ["textAnchor", "text-anchor"],
      ["textDecoration", "text-decoration"],
      ["textRendering", "text-rendering"],
      ["transformOrigin", "transform-origin"],
      ["underlinePosition", "underline-position"],
      ["underlineThickness", "underline-thickness"],
      ["unicodeBidi", "unicode-bidi"],
      ["unicodeRange", "unicode-range"],
      ["unitsPerEm", "units-per-em"],
      ["vAlphabetic", "v-alphabetic"],
      ["vHanging", "v-hanging"],
      ["vIdeographic", "v-ideographic"],
      ["vMathematical", "v-mathematical"],
      ["vectorEffect", "vector-effect"],
      ["vertAdvY", "vert-adv-y"],
      ["vertOriginX", "vert-origin-x"],
      ["vertOriginY", "vert-origin-y"],
      ["wordSpacing", "word-spacing"],
      ["writingMode", "writing-mode"],
      ["xmlnsXlink", "xmlns:xlink"],
      ["xHeight", "x-height"],
    ]),
    cd =
      /^[\u0000-\u001F ]*j[\r\n\t]*a[\r\n\t]*v[\r\n\t]*a[\r\n\t]*s[\r\n\t]*c[\r\n\t]*r[\r\n\t]*i[\r\n\t]*p[\r\n\t]*t[\r\n\t]*:/i;
  function qu(l) {
    return cd.test("" + l)
      ? "javascript:throw new Error('React has blocked a javascript: URL as a security precaution.')"
      : l;
  }
  function Rt() {}
  var fi = null;
  function si(l) {
    return (
      (l = l.target || l.srcElement || window),
      l.correspondingUseElement && (l = l.correspondingUseElement),
      l.nodeType === 3 ? l.parentNode : l
    );
  }
  var te = null,
    ae = null;
  function Kf(l) {
    var t = ka(l);
    if (t && (l = t.stateNode)) {
      var a = l[Vl] || null;
      l: switch (((l = t.stateNode), t.type)) {
        case "input":
          if (
            (ni(
              l,
              a.value,
              a.defaultValue,
              a.defaultValue,
              a.checked,
              a.defaultChecked,
              a.type,
              a.name,
            ),
            (t = a.name),
            a.type === "radio" && t != null)
          ) {
            for (a = l; a.parentNode;) a = a.parentNode;
            for (
              a = a.querySelectorAll('input[name="' + ot("" + t) + '"][type="radio"]'), t = 0;
              t < a.length;
              t++
            ) {
              var e = a[t];
              if (e !== l && e.form === l.form) {
                var u = e[Vl] || null;
                if (!u) throw Error(d(90));
                ni(
                  e,
                  u.value,
                  u.defaultValue,
                  u.defaultValue,
                  u.checked,
                  u.defaultChecked,
                  u.type,
                  u.name,
                );
              }
            }
            for (t = 0; t < a.length; t++) ((e = a[t]), e.form === l.form && Gf(e));
          }
          break l;
        case "textarea":
          Qf(l, a.value, a.defaultValue);
          break l;
        case "select":
          ((t = a.value), t != null && Pa(l, !!a.multiple, t, !1));
      }
    }
  }
  var oi = !1;
  function Jf(l, t, a) {
    if (oi) return l(t, a);
    oi = !0;
    try {
      var e = l(t);
      return e;
    } finally {
      if (
        ((oi = !1),
        (te !== null || ae !== null) &&
          (An(), te && ((t = te), (l = ae), (ae = te = null), Kf(t), l)))
      )
        for (t = 0; t < l.length; t++) Kf(l[t]);
    }
  }
  function Ye(l, t) {
    var a = l.stateNode;
    if (a === null) return null;
    var e = a[Vl] || null;
    if (e === null) return null;
    a = e[t];
    l: switch (t) {
      case "onClick":
      case "onClickCapture":
      case "onDoubleClick":
      case "onDoubleClickCapture":
      case "onMouseDown":
      case "onMouseDownCapture":
      case "onMouseMove":
      case "onMouseMoveCapture":
      case "onMouseUp":
      case "onMouseUpCapture":
      case "onMouseEnter":
        ((e = !e.disabled) ||
          ((l = l.type),
          (e = !(l === "button" || l === "input" || l === "select" || l === "textarea"))),
          (l = !e));
        break l;
      default:
        l = !1;
    }
    if (l) return null;
    if (a && typeof a != "function") throw Error(d(231, t, typeof a));
    return a;
  }
  var xt = !(
      typeof window > "u" ||
      typeof window.document > "u" ||
      typeof window.document.createElement > "u"
    ),
    mi = !1;
  if (xt)
    try {
      var Ge = {};
      (Object.defineProperty(Ge, "passive", {
        get: function () {
          mi = !0;
        },
      }),
        window.addEventListener("test", Ge, Ge),
        window.removeEventListener("test", Ge, Ge));
    } catch {
      mi = !1;
    }
  var la = null,
    di = null,
    Bu = null;
  function wf() {
    if (Bu) return Bu;
    var l,
      t = di,
      a = t.length,
      e,
      u = "value" in la ? la.value : la.textContent,
      n = u.length;
    for (l = 0; l < a && t[l] === u[l]; l++);
    var i = a - l;
    for (e = 1; e <= i && t[a - e] === u[n - e]; e++);
    return (Bu = u.slice(l, 1 < e ? 1 - e : void 0));
  }
  function Yu(l) {
    var t = l.keyCode;
    return (
      "charCode" in l ? ((l = l.charCode), l === 0 && t === 13 && (l = 13)) : (l = t),
      l === 10 && (l = 13),
      32 <= l || l === 13 ? l : 0
    );
  }
  function Gu() {
    return !0;
  }
  function Wf() {
    return !1;
  }
  function Ll(l) {
    function t(a, e, u, n, i) {
      ((this._reactName = a),
        (this._targetInst = u),
        (this.type = e),
        (this.nativeEvent = n),
        (this.target = i),
        (this.currentTarget = null));
      for (var c in l) l.hasOwnProperty(c) && ((a = l[c]), (this[c] = a ? a(n) : n[c]));
      return (
        (this.isDefaultPrevented = (
          n.defaultPrevented != null ? n.defaultPrevented : n.returnValue === !1
        )
          ? Gu
          : Wf),
        (this.isPropagationStopped = Wf),
        this
      );
    }
    return (
      B(t.prototype, {
        preventDefault: function () {
          this.defaultPrevented = !0;
          var a = this.nativeEvent;
          a &&
            (a.preventDefault
              ? a.preventDefault()
              : typeof a.returnValue != "unknown" && (a.returnValue = !1),
            (this.isDefaultPrevented = Gu));
        },
        stopPropagation: function () {
          var a = this.nativeEvent;
          a &&
            (a.stopPropagation
              ? a.stopPropagation()
              : typeof a.cancelBubble != "unknown" && (a.cancelBubble = !0),
            (this.isPropagationStopped = Gu));
        },
        persist: function () {},
        isPersistent: Gu,
      }),
      t
    );
  }
  var Ma = {
      eventPhase: 0,
      bubbles: 0,
      cancelable: 0,
      timeStamp: function (l) {
        return l.timeStamp || Date.now();
      },
      defaultPrevented: 0,
      isTrusted: 0,
    },
    Xu = Ll(Ma),
    Xe = B({}, Ma, { view: 0, detail: 0 }),
    fd = Ll(Xe),
    hi,
    yi,
    Qe,
    Qu = B({}, Xe, {
      screenX: 0,
      screenY: 0,
      clientX: 0,
      clientY: 0,
      pageX: 0,
      pageY: 0,
      ctrlKey: 0,
      shiftKey: 0,
      altKey: 0,
      metaKey: 0,
      getModifierState: ri,
      button: 0,
      buttons: 0,
      relatedTarget: function (l) {
        return l.relatedTarget === void 0
          ? l.fromElement === l.srcElement
            ? l.toElement
            : l.fromElement
          : l.relatedTarget;
      },
      movementX: function (l) {
        return "movementX" in l
          ? l.movementX
          : (l !== Qe &&
              (Qe && l.type === "mousemove"
                ? ((hi = l.screenX - Qe.screenX), (yi = l.screenY - Qe.screenY))
                : (yi = hi = 0),
              (Qe = l)),
            hi);
      },
      movementY: function (l) {
        return "movementY" in l ? l.movementY : yi;
      },
    }),
    $f = Ll(Qu),
    sd = B({}, Qu, { dataTransfer: 0 }),
    od = Ll(sd),
    md = B({}, Xe, { relatedTarget: 0 }),
    vi = Ll(md),
    dd = B({}, Ma, { animationName: 0, elapsedTime: 0, pseudoElement: 0 }),
    hd = Ll(dd),
    yd = B({}, Ma, {
      clipboardData: function (l) {
        return "clipboardData" in l ? l.clipboardData : window.clipboardData;
      },
    }),
    vd = Ll(yd),
    rd = B({}, Ma, { data: 0 }),
    kf = Ll(rd),
    gd = {
      Esc: "Escape",
      Spacebar: " ",
      Left: "ArrowLeft",
      Up: "ArrowUp",
      Right: "ArrowRight",
      Down: "ArrowDown",
      Del: "Delete",
      Win: "OS",
      Menu: "ContextMenu",
      Apps: "ContextMenu",
      Scroll: "ScrollLock",
      MozPrintableKey: "Unidentified",
    },
    Sd = {
      8: "Backspace",
      9: "Tab",
      12: "Clear",
      13: "Enter",
      16: "Shift",
      17: "Control",
      18: "Alt",
      19: "Pause",
      20: "CapsLock",
      27: "Escape",
      32: " ",
      33: "PageUp",
      34: "PageDown",
      35: "End",
      36: "Home",
      37: "ArrowLeft",
      38: "ArrowUp",
      39: "ArrowRight",
      40: "ArrowDown",
      45: "Insert",
      46: "Delete",
      112: "F1",
      113: "F2",
      114: "F3",
      115: "F4",
      116: "F5",
      117: "F6",
      118: "F7",
      119: "F8",
      120: "F9",
      121: "F10",
      122: "F11",
      123: "F12",
      144: "NumLock",
      145: "ScrollLock",
      224: "Meta",
    },
    bd = { Alt: "altKey", Control: "ctrlKey", Meta: "metaKey", Shift: "shiftKey" };
  function zd(l) {
    var t = this.nativeEvent;
    return t.getModifierState ? t.getModifierState(l) : (l = bd[l]) ? !!t[l] : !1;
  }
  function ri() {
    return zd;
  }
  var _d = B({}, Xe, {
      key: function (l) {
        if (l.key) {
          var t = gd[l.key] || l.key;
          if (t !== "Unidentified") return t;
        }
        return l.type === "keypress"
          ? ((l = Yu(l)), l === 13 ? "Enter" : String.fromCharCode(l))
          : l.type === "keydown" || l.type === "keyup"
            ? Sd[l.keyCode] || "Unidentified"
            : "";
      },
      code: 0,
      location: 0,
      ctrlKey: 0,
      shiftKey: 0,
      altKey: 0,
      metaKey: 0,
      repeat: 0,
      locale: 0,
      getModifierState: ri,
      charCode: function (l) {
        return l.type === "keypress" ? Yu(l) : 0;
      },
      keyCode: function (l) {
        return l.type === "keydown" || l.type === "keyup" ? l.keyCode : 0;
      },
      which: function (l) {
        return l.type === "keypress"
          ? Yu(l)
          : l.type === "keydown" || l.type === "keyup"
            ? l.keyCode
            : 0;
      },
    }),
    Td = Ll(_d),
    Ed = B({}, Qu, {
      pointerId: 0,
      width: 0,
      height: 0,
      pressure: 0,
      tangentialPressure: 0,
      tiltX: 0,
      tiltY: 0,
      twist: 0,
      pointerType: 0,
      isPrimary: 0,
    }),
    Ff = Ll(Ed),
    Ad = B({}, Xe, {
      touches: 0,
      targetTouches: 0,
      changedTouches: 0,
      altKey: 0,
      metaKey: 0,
      ctrlKey: 0,
      shiftKey: 0,
      getModifierState: ri,
    }),
    pd = Ll(Ad),
    Od = B({}, Ma, { propertyName: 0, elapsedTime: 0, pseudoElement: 0 }),
    Md = Ll(Od),
    Nd = B({}, Qu, {
      deltaX: function (l) {
        return "deltaX" in l ? l.deltaX : "wheelDeltaX" in l ? -l.wheelDeltaX : 0;
      },
      deltaY: function (l) {
        return "deltaY" in l
          ? l.deltaY
          : "wheelDeltaY" in l
            ? -l.wheelDeltaY
            : "wheelDelta" in l
              ? -l.wheelDelta
              : 0;
      },
      deltaZ: 0,
      deltaMode: 0,
    }),
    Dd = Ll(Nd),
    Ud = B({}, Ma, { newState: 0, oldState: 0 }),
    Hd = Ll(Ud),
    jd = [9, 13, 27, 32],
    gi = xt && "CompositionEvent" in window,
    Ze = null;
  xt && "documentMode" in document && (Ze = document.documentMode);
  var Rd = xt && "TextEvent" in window && !Ze,
    If = xt && (!gi || (Ze && 8 < Ze && 11 >= Ze)),
    Pf = " ",
    ls = !1;
  function ts(l, t) {
    switch (l) {
      case "keyup":
        return jd.indexOf(t.keyCode) !== -1;
      case "keydown":
        return t.keyCode !== 229;
      case "keypress":
      case "mousedown":
      case "focusout":
        return !0;
      default:
        return !1;
    }
  }
  function as(l) {
    return ((l = l.detail), typeof l == "object" && "data" in l ? l.data : null);
  }
  var ee = !1;
  function xd(l, t) {
    switch (l) {
      case "compositionend":
        return as(t);
      case "keypress":
        return t.which !== 32 ? null : ((ls = !0), Pf);
      case "textInput":
        return ((l = t.data), l === Pf && ls ? null : l);
      default:
        return null;
    }
  }
  function Cd(l, t) {
    if (ee)
      return l === "compositionend" || (!gi && ts(l, t))
        ? ((l = wf()), (Bu = di = la = null), (ee = !1), l)
        : null;
    switch (l) {
      case "paste":
        return null;
      case "keypress":
        if (!(t.ctrlKey || t.altKey || t.metaKey) || (t.ctrlKey && t.altKey)) {
          if (t.char && 1 < t.char.length) return t.char;
          if (t.which) return String.fromCharCode(t.which);
        }
        return null;
      case "compositionend":
        return If && t.locale !== "ko" ? null : t.data;
      default:
        return null;
    }
  }
  var qd = {
    color: !0,
    date: !0,
    datetime: !0,
    "datetime-local": !0,
    email: !0,
    month: !0,
    number: !0,
    password: !0,
    range: !0,
    search: !0,
    tel: !0,
    text: !0,
    time: !0,
    url: !0,
    week: !0,
  };
  function es(l) {
    var t = l && l.nodeName && l.nodeName.toLowerCase();
    return t === "input" ? !!qd[l.type] : t === "textarea";
  }
  function us(l, t, a, e) {
    (te ? (ae ? ae.push(e) : (ae = [e])) : (te = e),
      (t = Hn(t, "onChange")),
      0 < t.length &&
        ((a = new Xu("onChange", "change", null, a, e)), l.push({ event: a, listeners: t })));
  }
  var Ve = null,
    Le = null;
  function Bd(l) {
    Q0(l, 0);
  }
  function Zu(l) {
    var t = Be(l);
    if (Gf(t)) return l;
  }
  function ns(l, t) {
    if (l === "change") return t;
  }
  var is = !1;
  if (xt) {
    var Si;
    if (xt) {
      var bi = "oninput" in document;
      if (!bi) {
        var cs = document.createElement("div");
        (cs.setAttribute("oninput", "return;"), (bi = typeof cs.oninput == "function"));
      }
      Si = bi;
    } else Si = !1;
    is = Si && (!document.documentMode || 9 < document.documentMode);
  }
  function fs() {
    Ve && (Ve.detachEvent("onpropertychange", ss), (Le = Ve = null));
  }
  function ss(l) {
    if (l.propertyName === "value" && Zu(Le)) {
      var t = [];
      (us(t, Le, l, si(l)), Jf(Bd, t));
    }
  }
  function Yd(l, t, a) {
    l === "focusin"
      ? (fs(), (Ve = t), (Le = a), Ve.attachEvent("onpropertychange", ss))
      : l === "focusout" && fs();
  }
  function Gd(l) {
    if (l === "selectionchange" || l === "keyup" || l === "keydown") return Zu(Le);
  }
  function Xd(l, t) {
    if (l === "click") return Zu(t);
  }
  function Qd(l, t) {
    if (l === "input" || l === "change") return Zu(t);
  }
  function Zd(l, t) {
    return (l === t && (l !== 0 || 1 / l === 1 / t)) || (l !== l && t !== t);
  }
  var tt = typeof Object.is == "function" ? Object.is : Zd;
  function Ke(l, t) {
    if (tt(l, t)) return !0;
    if (typeof l != "object" || l === null || typeof t != "object" || t === null) return !1;
    var a = Object.keys(l),
      e = Object.keys(t);
    if (a.length !== e.length) return !1;
    for (e = 0; e < a.length; e++) {
      var u = a[e];
      if (!kn.call(t, u) || !tt(l[u], t[u])) return !1;
    }
    return !0;
  }
  function os(l) {
    for (; l && l.firstChild;) l = l.firstChild;
    return l;
  }
  function ms(l, t) {
    var a = os(l);
    l = 0;
    for (var e; a;) {
      if (a.nodeType === 3) {
        if (((e = l + a.textContent.length), l <= t && e >= t)) return { node: a, offset: t - l };
        l = e;
      }
      l: {
        for (; a;) {
          if (a.nextSibling) {
            a = a.nextSibling;
            break l;
          }
          a = a.parentNode;
        }
        a = void 0;
      }
      a = os(a);
    }
  }
  function ds(l, t) {
    return l && t
      ? l === t
        ? !0
        : l && l.nodeType === 3
          ? !1
          : t && t.nodeType === 3
            ? ds(l, t.parentNode)
            : "contains" in l
              ? l.contains(t)
              : l.compareDocumentPosition
                ? !!(l.compareDocumentPosition(t) & 16)
                : !1
      : !1;
  }
  function hs(l) {
    l =
      l != null && l.ownerDocument != null && l.ownerDocument.defaultView != null
        ? l.ownerDocument.defaultView
        : window;
    for (var t = Cu(l.document); t instanceof l.HTMLIFrameElement;) {
      try {
        var a = typeof t.contentWindow.location.href == "string";
      } catch {
        a = !1;
      }
      if (a) l = t.contentWindow;
      else break;
      t = Cu(l.document);
    }
    return t;
  }
  function zi(l) {
    var t = l && l.nodeName && l.nodeName.toLowerCase();
    return (
      t &&
      ((t === "input" &&
        (l.type === "text" ||
          l.type === "search" ||
          l.type === "tel" ||
          l.type === "url" ||
          l.type === "password")) ||
        t === "textarea" ||
        l.contentEditable === "true")
    );
  }
  var Vd = xt && "documentMode" in document && 11 >= document.documentMode,
    ue = null,
    _i = null,
    Je = null,
    Ti = !1;
  function ys(l, t, a) {
    var e = a.window === a ? a.document : a.nodeType === 9 ? a : a.ownerDocument;
    Ti ||
      ue == null ||
      ue !== Cu(e) ||
      ((e = ue),
      "selectionStart" in e && zi(e)
        ? (e = { start: e.selectionStart, end: e.selectionEnd })
        : ((e = ((e.ownerDocument && e.ownerDocument.defaultView) || window).getSelection()),
          (e = {
            anchorNode: e.anchorNode,
            anchorOffset: e.anchorOffset,
            focusNode: e.focusNode,
            focusOffset: e.focusOffset,
          })),
      (Je && Ke(Je, e)) ||
        ((Je = e),
        (e = Hn(_i, "onSelect")),
        0 < e.length &&
          ((t = new Xu("onSelect", "select", null, t, a)),
          l.push({ event: t, listeners: e }),
          (t.target = ue))));
  }
  function Na(l, t) {
    var a = {};
    return (
      (a[l.toLowerCase()] = t.toLowerCase()),
      (a["Webkit" + l] = "webkit" + t),
      (a["Moz" + l] = "moz" + t),
      a
    );
  }
  var ne = {
      animationend: Na("Animation", "AnimationEnd"),
      animationiteration: Na("Animation", "AnimationIteration"),
      animationstart: Na("Animation", "AnimationStart"),
      transitionrun: Na("Transition", "TransitionRun"),
      transitionstart: Na("Transition", "TransitionStart"),
      transitioncancel: Na("Transition", "TransitionCancel"),
      transitionend: Na("Transition", "TransitionEnd"),
    },
    Ei = {},
    vs = {};
  xt &&
    ((vs = document.createElement("div").style),
    "AnimationEvent" in window ||
      (delete ne.animationend.animation,
      delete ne.animationiteration.animation,
      delete ne.animationstart.animation),
    "TransitionEvent" in window || delete ne.transitionend.transition);
  function Da(l) {
    if (Ei[l]) return Ei[l];
    if (!ne[l]) return l;
    var t = ne[l],
      a;
    for (a in t) if (t.hasOwnProperty(a) && a in vs) return (Ei[l] = t[a]);
    return l;
  }
  var rs = Da("animationend"),
    gs = Da("animationiteration"),
    Ss = Da("animationstart"),
    Ld = Da("transitionrun"),
    Kd = Da("transitionstart"),
    Jd = Da("transitioncancel"),
    bs = Da("transitionend"),
    zs = new Map(),
    Ai =
      "abort auxClick beforeToggle cancel canPlay canPlayThrough click close contextMenu copy cut drag dragEnd dragEnter dragExit dragLeave dragOver dragStart drop durationChange emptied encrypted ended error gotPointerCapture input invalid keyDown keyPress keyUp load loadedData loadedMetadata loadStart lostPointerCapture mouseDown mouseMove mouseOut mouseOver mouseUp paste pause play playing pointerCancel pointerDown pointerMove pointerOut pointerOver pointerUp progress rateChange reset resize seeked seeking stalled submit suspend timeUpdate touchCancel touchEnd touchStart volumeChange scroll toggle touchMove waiting wheel".split(
        " ",
      );
  Ai.push("scrollEnd");
  function zt(l, t) {
    (zs.set(l, t), Oa(t, [l]));
  }
  var Vu =
      typeof reportError == "function"
        ? reportError
        : function (l) {
            if (typeof window == "object" && typeof window.ErrorEvent == "function") {
              var t = new window.ErrorEvent("error", {
                bubbles: !0,
                cancelable: !0,
                message:
                  typeof l == "object" && l !== null && typeof l.message == "string"
                    ? String(l.message)
                    : String(l),
                error: l,
              });
              if (!window.dispatchEvent(t)) return;
            } else if (typeof process == "object" && typeof process.emit == "function") {
              process.emit("uncaughtException", l);
              return;
            }
            console.error(l);
          },
    mt = [],
    ie = 0,
    pi = 0;
  function Lu() {
    for (var l = ie, t = (pi = ie = 0); t < l;) {
      var a = mt[t];
      mt[t++] = null;
      var e = mt[t];
      mt[t++] = null;
      var u = mt[t];
      mt[t++] = null;
      var n = mt[t];
      if (((mt[t++] = null), e !== null && u !== null)) {
        var i = e.pending;
        (i === null ? (u.next = u) : ((u.next = i.next), (i.next = u)), (e.pending = u));
      }
      n !== 0 && _s(a, u, n);
    }
  }
  function Ku(l, t, a, e) {
    ((mt[ie++] = l),
      (mt[ie++] = t),
      (mt[ie++] = a),
      (mt[ie++] = e),
      (pi |= e),
      (l.lanes |= e),
      (l = l.alternate),
      l !== null && (l.lanes |= e));
  }
  function Oi(l, t, a, e) {
    return (Ku(l, t, a, e), Ju(l));
  }
  function Ua(l, t) {
    return (Ku(l, null, null, t), Ju(l));
  }
  function _s(l, t, a) {
    l.lanes |= a;
    var e = l.alternate;
    e !== null && (e.lanes |= a);
    for (var u = !1, n = l.return; n !== null;)
      ((n.childLanes |= a),
        (e = n.alternate),
        e !== null && (e.childLanes |= a),
        n.tag === 22 && ((l = n.stateNode), l === null || l._visibility & 1 || (u = !0)),
        (l = n),
        (n = n.return));
    return l.tag === 3
      ? ((n = l.stateNode),
        u &&
          t !== null &&
          ((u = 31 - lt(a)),
          (l = n.hiddenUpdates),
          (e = l[u]),
          e === null ? (l[u] = [t]) : e.push(t),
          (t.lane = a | 536870912)),
        n)
      : null;
  }
  function Ju(l) {
    if (50 < yu) throw ((yu = 0), (Cc = null), Error(d(185)));
    for (var t = l.return; t !== null;) ((l = t), (t = l.return));
    return l.tag === 3 ? l.stateNode : null;
  }
  var ce = {};
  function wd(l, t, a, e) {
    ((this.tag = l),
      (this.key = a),
      (this.sibling =
        this.child =
        this.return =
        this.stateNode =
        this.type =
        this.elementType =
          null),
      (this.index = 0),
      (this.refCleanup = this.ref = null),
      (this.pendingProps = t),
      (this.dependencies = this.memoizedState = this.updateQueue = this.memoizedProps = null),
      (this.mode = e),
      (this.subtreeFlags = this.flags = 0),
      (this.deletions = null),
      (this.childLanes = this.lanes = 0),
      (this.alternate = null));
  }
  function at(l, t, a, e) {
    return new wd(l, t, a, e);
  }
  function Mi(l) {
    return ((l = l.prototype), !(!l || !l.isReactComponent));
  }
  function Ct(l, t) {
    var a = l.alternate;
    return (
      a === null
        ? ((a = at(l.tag, t, l.key, l.mode)),
          (a.elementType = l.elementType),
          (a.type = l.type),
          (a.stateNode = l.stateNode),
          (a.alternate = l),
          (l.alternate = a))
        : ((a.pendingProps = t),
          (a.type = l.type),
          (a.flags = 0),
          (a.subtreeFlags = 0),
          (a.deletions = null)),
      (a.flags = l.flags & 65011712),
      (a.childLanes = l.childLanes),
      (a.lanes = l.lanes),
      (a.child = l.child),
      (a.memoizedProps = l.memoizedProps),
      (a.memoizedState = l.memoizedState),
      (a.updateQueue = l.updateQueue),
      (t = l.dependencies),
      (a.dependencies = t === null ? null : { lanes: t.lanes, firstContext: t.firstContext }),
      (a.sibling = l.sibling),
      (a.index = l.index),
      (a.ref = l.ref),
      (a.refCleanup = l.refCleanup),
      a
    );
  }
  function Ts(l, t) {
    l.flags &= 65011714;
    var a = l.alternate;
    return (
      a === null
        ? ((l.childLanes = 0),
          (l.lanes = t),
          (l.child = null),
          (l.subtreeFlags = 0),
          (l.memoizedProps = null),
          (l.memoizedState = null),
          (l.updateQueue = null),
          (l.dependencies = null),
          (l.stateNode = null))
        : ((l.childLanes = a.childLanes),
          (l.lanes = a.lanes),
          (l.child = a.child),
          (l.subtreeFlags = 0),
          (l.deletions = null),
          (l.memoizedProps = a.memoizedProps),
          (l.memoizedState = a.memoizedState),
          (l.updateQueue = a.updateQueue),
          (l.type = a.type),
          (t = a.dependencies),
          (l.dependencies = t === null ? null : { lanes: t.lanes, firstContext: t.firstContext })),
      l
    );
  }
  function wu(l, t, a, e, u, n) {
    var i = 0;
    if (((e = l), typeof l == "function")) Mi(l) && (i = 1);
    else if (typeof l == "string")
      i = Ih(l, a, U.current) ? 26 : l === "html" || l === "head" || l === "body" ? 27 : 5;
    else
      l: switch (l) {
        case At:
          return ((l = at(31, a, t, u)), (l.elementType = At), (l.lanes = n), l);
        case ql:
          return Ha(a.children, u, n, t);
        case Ut:
          ((i = 8), (u |= 24));
          break;
        case Fl:
          return ((l = at(12, a, t, u | 2)), (l.elementType = Fl), (l.lanes = n), l);
        case Et:
          return ((l = at(13, a, t, u)), (l.elementType = Et), (l.lanes = n), l);
        case Xl:
          return ((l = at(19, a, t, u)), (l.elementType = Xl), (l.lanes = n), l);
        default:
          if (typeof l == "object" && l !== null)
            switch (l.$$typeof) {
              case xl:
                i = 10;
                break l;
              case Ft:
                i = 9;
                break l;
              case ft:
                i = 11;
                break l;
              case $:
                i = 14;
                break l;
              case Ql:
                ((i = 16), (e = null));
                break l;
            }
          ((i = 29), (a = Error(d(130, l === null ? "null" : typeof l, ""))), (e = null));
      }
    return ((t = at(i, a, t, u)), (t.elementType = l), (t.type = e), (t.lanes = n), t);
  }
  function Ha(l, t, a, e) {
    return ((l = at(7, l, e, t)), (l.lanes = a), l);
  }
  function Ni(l, t, a) {
    return ((l = at(6, l, null, t)), (l.lanes = a), l);
  }
  function Es(l) {
    var t = at(18, null, null, 0);
    return ((t.stateNode = l), t);
  }
  function Di(l, t, a) {
    return (
      (t = at(4, l.children !== null ? l.children : [], l.key, t)),
      (t.lanes = a),
      (t.stateNode = {
        containerInfo: l.containerInfo,
        pendingChildren: null,
        implementation: l.implementation,
      }),
      t
    );
  }
  var As = new WeakMap();
  function dt(l, t) {
    if (typeof l == "object" && l !== null) {
      var a = As.get(l);
      return a !== void 0 ? a : ((t = { value: l, source: t, stack: Ef(t) }), As.set(l, t), t);
    }
    return { value: l, source: t, stack: Ef(t) };
  }
  var fe = [],
    se = 0,
    Wu = null,
    we = 0,
    ht = [],
    yt = 0,
    ta = null,
    Ot = 1,
    Mt = "";
  function qt(l, t) {
    ((fe[se++] = we), (fe[se++] = Wu), (Wu = l), (we = t));
  }
  function ps(l, t, a) {
    ((ht[yt++] = Ot), (ht[yt++] = Mt), (ht[yt++] = ta), (ta = l));
    var e = Ot;
    l = Mt;
    var u = 32 - lt(e) - 1;
    ((e &= ~(1 << u)), (a += 1));
    var n = 32 - lt(t) + u;
    if (30 < n) {
      var i = u - (u % 5);
      ((n = (e & ((1 << i) - 1)).toString(32)),
        (e >>= i),
        (u -= i),
        (Ot = (1 << (32 - lt(t) + u)) | (a << u) | e),
        (Mt = n + l));
    } else ((Ot = (1 << n) | (a << u) | e), (Mt = l));
  }
  function Ui(l) {
    l.return !== null && (qt(l, 1), ps(l, 1, 0));
  }
  function Hi(l) {
    for (; l === Wu;) ((Wu = fe[--se]), (fe[se] = null), (we = fe[--se]), (fe[se] = null));
    for (; l === ta;)
      ((ta = ht[--yt]),
        (ht[yt] = null),
        (Mt = ht[--yt]),
        (ht[yt] = null),
        (Ot = ht[--yt]),
        (ht[yt] = null));
  }
  function Os(l, t) {
    ((ht[yt++] = Ot), (ht[yt++] = Mt), (ht[yt++] = ta), (Ot = t.id), (Mt = t.overflow), (ta = l));
  }
  var Ul = null,
    ol = null,
    k = !1,
    aa = null,
    vt = !1,
    ji = Error(d(519));
  function ea(l) {
    var t = Error(
      d(418, 1 < arguments.length && arguments[1] !== void 0 && arguments[1] ? "text" : "HTML", ""),
    );
    throw (We(dt(t, l)), ji);
  }
  function Ms(l) {
    var t = l.stateNode,
      a = l.type,
      e = l.memoizedProps;
    switch (((t[Dl] = l), (t[Vl] = e), a)) {
      case "dialog":
        (J("cancel", t), J("close", t));
        break;
      case "iframe":
      case "object":
      case "embed":
        J("load", t);
        break;
      case "video":
      case "audio":
        for (a = 0; a < ru.length; a++) J(ru[a], t);
        break;
      case "source":
        J("error", t);
        break;
      case "img":
      case "image":
      case "link":
        (J("error", t), J("load", t));
        break;
      case "details":
        J("toggle", t);
        break;
      case "input":
        (J("invalid", t),
          Xf(t, e.value, e.defaultValue, e.checked, e.defaultChecked, e.type, e.name, !0));
        break;
      case "select":
        J("invalid", t);
        break;
      case "textarea":
        (J("invalid", t), Zf(t, e.value, e.defaultValue, e.children));
    }
    ((a = e.children),
      (typeof a != "string" && typeof a != "number" && typeof a != "bigint") ||
      t.textContent === "" + a ||
      e.suppressHydrationWarning === !0 ||
      K0(t.textContent, a)
        ? (e.popover != null && (J("beforetoggle", t), J("toggle", t)),
          e.onScroll != null && J("scroll", t),
          e.onScrollEnd != null && J("scrollend", t),
          e.onClick != null && (t.onclick = Rt),
          (t = !0))
        : (t = !1),
      t || ea(l, !0));
  }
  function Ns(l) {
    for (Ul = l.return; Ul;)
      switch (Ul.tag) {
        case 5:
        case 31:
        case 13:
          vt = !1;
          return;
        case 27:
        case 3:
          vt = !0;
          return;
        default:
          Ul = Ul.return;
      }
  }
  function oe(l) {
    if (l !== Ul) return !1;
    if (!k) return (Ns(l), (k = !0), !1);
    var t = l.tag,
      a;
    if (
      ((a = t !== 3 && t !== 27) &&
        ((a = t === 5) &&
          ((a = l.type), (a = !(a !== "form" && a !== "button") || kc(l.type, l.memoizedProps))),
        (a = !a)),
      a && ol && ea(l),
      Ns(l),
      t === 13)
    ) {
      if (((l = l.memoizedState), (l = l !== null ? l.dehydrated : null), !l)) throw Error(d(317));
      ol = lm(l);
    } else if (t === 31) {
      if (((l = l.memoizedState), (l = l !== null ? l.dehydrated : null), !l)) throw Error(d(317));
      ol = lm(l);
    } else
      t === 27
        ? ((t = ol), ga(l.type) ? ((l = tf), (tf = null), (ol = l)) : (ol = t))
        : (ol = Ul ? gt(l.stateNode.nextSibling) : null);
    return !0;
  }
  function ja() {
    ((ol = Ul = null), (k = !1));
  }
  function Ri() {
    var l = aa;
    return (l !== null && (Wl === null ? (Wl = l) : Wl.push.apply(Wl, l), (aa = null)), l);
  }
  function We(l) {
    aa === null ? (aa = [l]) : aa.push(l);
  }
  var xi = o(null),
    Ra = null,
    Bt = null;
  function ua(l, t, a) {
    (O(xi, t._currentValue), (t._currentValue = a));
  }
  function Yt(l) {
    ((l._currentValue = xi.current), T(xi));
  }
  function Ci(l, t, a) {
    for (; l !== null;) {
      var e = l.alternate;
      if (
        ((l.childLanes & t) !== t
          ? ((l.childLanes |= t), e !== null && (e.childLanes |= t))
          : e !== null && (e.childLanes & t) !== t && (e.childLanes |= t),
        l === a)
      )
        break;
      l = l.return;
    }
  }
  function qi(l, t, a, e) {
    var u = l.child;
    for (u !== null && (u.return = l); u !== null;) {
      var n = u.dependencies;
      if (n !== null) {
        var i = u.child;
        n = n.firstContext;
        l: for (; n !== null;) {
          var c = n;
          n = u;
          for (var f = 0; f < t.length; f++)
            if (c.context === t[f]) {
              ((n.lanes |= a),
                (c = n.alternate),
                c !== null && (c.lanes |= a),
                Ci(n.return, a, l),
                e || (i = null));
              break l;
            }
          n = c.next;
        }
      } else if (u.tag === 18) {
        if (((i = u.return), i === null)) throw Error(d(341));
        ((i.lanes |= a), (n = i.alternate), n !== null && (n.lanes |= a), Ci(i, a, l), (i = null));
      } else i = u.child;
      if (i !== null) i.return = u;
      else
        for (i = u; i !== null;) {
          if (i === l) {
            i = null;
            break;
          }
          if (((u = i.sibling), u !== null)) {
            ((u.return = i.return), (i = u));
            break;
          }
          i = i.return;
        }
      u = i;
    }
  }
  function me(l, t, a, e) {
    l = null;
    for (var u = t, n = !1; u !== null;) {
      if (!n) {
        if ((u.flags & 524288) !== 0) n = !0;
        else if ((u.flags & 262144) !== 0) break;
      }
      if (u.tag === 10) {
        var i = u.alternate;
        if (i === null) throw Error(d(387));
        if (((i = i.memoizedProps), i !== null)) {
          var c = u.type;
          tt(u.pendingProps.value, i.value) || (l !== null ? l.push(c) : (l = [c]));
        }
      } else if (u === tl.current) {
        if (((i = u.alternate), i === null)) throw Error(d(387));
        i.memoizedState.memoizedState !== u.memoizedState.memoizedState &&
          (l !== null ? l.push(_u) : (l = [_u]));
      }
      u = u.return;
    }
    (l !== null && qi(t, l, a, e), (t.flags |= 262144));
  }
  function $u(l) {
    for (l = l.firstContext; l !== null;) {
      if (!tt(l.context._currentValue, l.memoizedValue)) return !0;
      l = l.next;
    }
    return !1;
  }
  function xa(l) {
    ((Ra = l), (Bt = null), (l = l.dependencies), l !== null && (l.firstContext = null));
  }
  function Hl(l) {
    return Ds(Ra, l);
  }
  function ku(l, t) {
    return (Ra === null && xa(l), Ds(l, t));
  }
  function Ds(l, t) {
    var a = t._currentValue;
    if (((t = { context: t, memoizedValue: a, next: null }), Bt === null)) {
      if (l === null) throw Error(d(308));
      ((Bt = t), (l.dependencies = { lanes: 0, firstContext: t }), (l.flags |= 524288));
    } else Bt = Bt.next = t;
    return a;
  }
  var Wd =
      typeof AbortController < "u"
        ? AbortController
        : function () {
            var l = [],
              t = (this.signal = {
                aborted: !1,
                addEventListener: function (a, e) {
                  l.push(e);
                },
              });
            this.abort = function () {
              ((t.aborted = !0),
                l.forEach(function (a) {
                  return a();
                }));
            };
          },
    $d = b.unstable_scheduleCallback,
    kd = b.unstable_NormalPriority,
    _l = {
      $$typeof: xl,
      Consumer: null,
      Provider: null,
      _currentValue: null,
      _currentValue2: null,
      _threadCount: 0,
    };
  function Bi() {
    return { controller: new Wd(), data: new Map(), refCount: 0 };
  }
  function $e(l) {
    (l.refCount--,
      l.refCount === 0 &&
        $d(kd, function () {
          l.controller.abort();
        }));
  }
  var ke = null,
    Yi = 0,
    de = 0,
    he = null;
  function Fd(l, t) {
    if (ke === null) {
      var a = (ke = []);
      ((Yi = 0),
        (de = Qc()),
        (he = {
          status: "pending",
          value: void 0,
          then: function (e) {
            a.push(e);
          },
        }));
    }
    return (Yi++, t.then(Us, Us), t);
  }
  function Us() {
    if (--Yi === 0 && ke !== null) {
      he !== null && (he.status = "fulfilled");
      var l = ke;
      ((ke = null), (de = 0), (he = null));
      for (var t = 0; t < l.length; t++) (0, l[t])();
    }
  }
  function Id(l, t) {
    var a = [],
      e = {
        status: "pending",
        value: null,
        reason: null,
        then: function (u) {
          a.push(u);
        },
      };
    return (
      l.then(
        function () {
          ((e.status = "fulfilled"), (e.value = t));
          for (var u = 0; u < a.length; u++) (0, a[u])(t);
        },
        function (u) {
          for (e.status = "rejected", e.reason = u, u = 0; u < a.length; u++) (0, a[u])(void 0);
        },
      ),
      e
    );
  }
  var Hs = S.S;
  S.S = function (l, t) {
    ((v0 = Il()),
      typeof t == "object" && t !== null && typeof t.then == "function" && Fd(l, t),
      Hs !== null && Hs(l, t));
  };
  var Ca = o(null);
  function Gi() {
    var l = Ca.current;
    return l !== null ? l : sl.pooledCache;
  }
  function Fu(l, t) {
    t === null ? O(Ca, Ca.current) : O(Ca, t.pool);
  }
  function js() {
    var l = Gi();
    return l === null ? null : { parent: _l._currentValue, pool: l };
  }
  var ye = Error(d(460)),
    Xi = Error(d(474)),
    Iu = Error(d(542)),
    Pu = { then: function () {} };
  function Rs(l) {
    return ((l = l.status), l === "fulfilled" || l === "rejected");
  }
  function xs(l, t, a) {
    switch (
      ((a = l[a]), a === void 0 ? l.push(t) : a !== t && (t.then(Rt, Rt), (t = a)), t.status)
    ) {
      case "fulfilled":
        return t.value;
      case "rejected":
        throw ((l = t.reason), qs(l), l);
      default:
        if (typeof t.status == "string") t.then(Rt, Rt);
        else {
          if (((l = sl), l !== null && 100 < l.shellSuspendCounter)) throw Error(d(482));
          ((l = t),
            (l.status = "pending"),
            l.then(
              function (e) {
                if (t.status === "pending") {
                  var u = t;
                  ((u.status = "fulfilled"), (u.value = e));
                }
              },
              function (e) {
                if (t.status === "pending") {
                  var u = t;
                  ((u.status = "rejected"), (u.reason = e));
                }
              },
            ));
        }
        switch (t.status) {
          case "fulfilled":
            return t.value;
          case "rejected":
            throw ((l = t.reason), qs(l), l);
        }
        throw ((Ba = t), ye);
    }
  }
  function qa(l) {
    try {
      var t = l._init;
      return t(l._payload);
    } catch (a) {
      throw a !== null && typeof a == "object" && typeof a.then == "function" ? ((Ba = a), ye) : a;
    }
  }
  var Ba = null;
  function Cs() {
    if (Ba === null) throw Error(d(459));
    var l = Ba;
    return ((Ba = null), l);
  }
  function qs(l) {
    if (l === ye || l === Iu) throw Error(d(483));
  }
  var ve = null,
    Fe = 0;
  function ln(l) {
    var t = Fe;
    return ((Fe += 1), ve === null && (ve = []), xs(ve, l, t));
  }
  function Ie(l, t) {
    ((t = t.props.ref), (l.ref = t !== void 0 ? t : null));
  }
  function tn(l, t) {
    throw t.$$typeof === dl
      ? Error(d(525))
      : ((l = Object.prototype.toString.call(t)),
        Error(
          d(
            31,
            l === "[object Object]" ? "object with keys {" + Object.keys(t).join(", ") + "}" : l,
          ),
        ));
  }
  function Bs(l) {
    function t(m, s) {
      if (l) {
        var h = m.deletions;
        h === null ? ((m.deletions = [s]), (m.flags |= 16)) : h.push(s);
      }
    }
    function a(m, s) {
      if (!l) return null;
      for (; s !== null;) (t(m, s), (s = s.sibling));
      return null;
    }
    function e(m) {
      for (var s = new Map(); m !== null;)
        (m.key !== null ? s.set(m.key, m) : s.set(m.index, m), (m = m.sibling));
      return s;
    }
    function u(m, s) {
      return ((m = Ct(m, s)), (m.index = 0), (m.sibling = null), m);
    }
    function n(m, s, h) {
      return (
        (m.index = h),
        l
          ? ((h = m.alternate),
            h !== null
              ? ((h = h.index), h < s ? ((m.flags |= 67108866), s) : h)
              : ((m.flags |= 67108866), s))
          : ((m.flags |= 1048576), s)
      );
    }
    function i(m) {
      return (l && m.alternate === null && (m.flags |= 67108866), m);
    }
    function c(m, s, h, z) {
      return s === null || s.tag !== 6
        ? ((s = Ni(h, m.mode, z)), (s.return = m), s)
        : ((s = u(s, h)), (s.return = m), s);
    }
    function f(m, s, h, z) {
      var x = h.type;
      return x === ql
        ? g(m, s, h.props.children, z, h.key)
        : s !== null &&
            (s.elementType === x ||
              (typeof x == "object" && x !== null && x.$$typeof === Ql && qa(x) === s.type))
          ? ((s = u(s, h.props)), Ie(s, h), (s.return = m), s)
          : ((s = wu(h.type, h.key, h.props, null, m.mode, z)), Ie(s, h), (s.return = m), s);
    }
    function y(m, s, h, z) {
      return s === null ||
        s.tag !== 4 ||
        s.stateNode.containerInfo !== h.containerInfo ||
        s.stateNode.implementation !== h.implementation
        ? ((s = Di(h, m.mode, z)), (s.return = m), s)
        : ((s = u(s, h.children || [])), (s.return = m), s);
    }
    function g(m, s, h, z, x) {
      return s === null || s.tag !== 7
        ? ((s = Ha(h, m.mode, z, x)), (s.return = m), s)
        : ((s = u(s, h)), (s.return = m), s);
    }
    function _(m, s, h) {
      if ((typeof s == "string" && s !== "") || typeof s == "number" || typeof s == "bigint")
        return ((s = Ni("" + s, m.mode, h)), (s.return = m), s);
      if (typeof s == "object" && s !== null) {
        switch (s.$$typeof) {
          case kl:
            return ((h = wu(s.type, s.key, s.props, null, m.mode, h)), Ie(h, s), (h.return = m), h);
          case Gl:
            return ((s = Di(s, m.mode, h)), (s.return = m), s);
          case Ql:
            return ((s = qa(s)), _(m, s, h));
        }
        if (bt(s) || Zl(s)) return ((s = Ha(s, m.mode, h, null)), (s.return = m), s);
        if (typeof s.then == "function") return _(m, ln(s), h);
        if (s.$$typeof === xl) return _(m, ku(m, s), h);
        tn(m, s);
      }
      return null;
    }
    function v(m, s, h, z) {
      var x = s !== null ? s.key : null;
      if ((typeof h == "string" && h !== "") || typeof h == "number" || typeof h == "bigint")
        return x !== null ? null : c(m, s, "" + h, z);
      if (typeof h == "object" && h !== null) {
        switch (h.$$typeof) {
          case kl:
            return h.key === x ? f(m, s, h, z) : null;
          case Gl:
            return h.key === x ? y(m, s, h, z) : null;
          case Ql:
            return ((h = qa(h)), v(m, s, h, z));
        }
        if (bt(h) || Zl(h)) return x !== null ? null : g(m, s, h, z, null);
        if (typeof h.then == "function") return v(m, s, ln(h), z);
        if (h.$$typeof === xl) return v(m, s, ku(m, h), z);
        tn(m, h);
      }
      return null;
    }
    function r(m, s, h, z, x) {
      if ((typeof z == "string" && z !== "") || typeof z == "number" || typeof z == "bigint")
        return ((m = m.get(h) || null), c(s, m, "" + z, x));
      if (typeof z == "object" && z !== null) {
        switch (z.$$typeof) {
          case kl:
            return ((m = m.get(z.key === null ? h : z.key) || null), f(s, m, z, x));
          case Gl:
            return ((m = m.get(z.key === null ? h : z.key) || null), y(s, m, z, x));
          case Ql:
            return ((z = qa(z)), r(m, s, h, z, x));
        }
        if (bt(z) || Zl(z)) return ((m = m.get(h) || null), g(s, m, z, x, null));
        if (typeof z.then == "function") return r(m, s, h, ln(z), x);
        if (z.$$typeof === xl) return r(m, s, h, ku(s, z), x);
        tn(s, z);
      }
      return null;
    }
    function M(m, s, h, z) {
      for (var x = null, F = null, H = s, Z = (s = 0), W = null; H !== null && Z < h.length; Z++) {
        H.index > Z ? ((W = H), (H = null)) : (W = H.sibling);
        var I = v(m, H, h[Z], z);
        if (I === null) {
          H === null && (H = W);
          break;
        }
        (l && H && I.alternate === null && t(m, H),
          (s = n(I, s, Z)),
          F === null ? (x = I) : (F.sibling = I),
          (F = I),
          (H = W));
      }
      if (Z === h.length) return (a(m, H), k && qt(m, Z), x);
      if (H === null) {
        for (; Z < h.length; Z++)
          ((H = _(m, h[Z], z)),
            H !== null && ((s = n(H, s, Z)), F === null ? (x = H) : (F.sibling = H), (F = H)));
        return (k && qt(m, Z), x);
      }
      for (H = e(H); Z < h.length; Z++)
        ((W = r(H, m, Z, h[Z], z)),
          W !== null &&
            (l && W.alternate !== null && H.delete(W.key === null ? Z : W.key),
            (s = n(W, s, Z)),
            F === null ? (x = W) : (F.sibling = W),
            (F = W)));
      return (
        l &&
          H.forEach(function (Ta) {
            return t(m, Ta);
          }),
        k && qt(m, Z),
        x
      );
    }
    function C(m, s, h, z) {
      if (h == null) throw Error(d(151));
      for (
        var x = null, F = null, H = s, Z = (s = 0), W = null, I = h.next();
        H !== null && !I.done;
        Z++, I = h.next()
      ) {
        H.index > Z ? ((W = H), (H = null)) : (W = H.sibling);
        var Ta = v(m, H, I.value, z);
        if (Ta === null) {
          H === null && (H = W);
          break;
        }
        (l && H && Ta.alternate === null && t(m, H),
          (s = n(Ta, s, Z)),
          F === null ? (x = Ta) : (F.sibling = Ta),
          (F = Ta),
          (H = W));
      }
      if (I.done) return (a(m, H), k && qt(m, Z), x);
      if (H === null) {
        for (; !I.done; Z++, I = h.next())
          ((I = _(m, I.value, z)),
            I !== null && ((s = n(I, s, Z)), F === null ? (x = I) : (F.sibling = I), (F = I)));
        return (k && qt(m, Z), x);
      }
      for (H = e(H); !I.done; Z++, I = h.next())
        ((I = r(H, m, Z, I.value, z)),
          I !== null &&
            (l && I.alternate !== null && H.delete(I.key === null ? Z : I.key),
            (s = n(I, s, Z)),
            F === null ? (x = I) : (F.sibling = I),
            (F = I)));
      return (
        l &&
          H.forEach(function (sy) {
            return t(m, sy);
          }),
        k && qt(m, Z),
        x
      );
    }
    function cl(m, s, h, z) {
      if (
        (typeof h == "object" &&
          h !== null &&
          h.type === ql &&
          h.key === null &&
          (h = h.props.children),
        typeof h == "object" && h !== null)
      ) {
        switch (h.$$typeof) {
          case kl:
            l: {
              for (var x = h.key; s !== null;) {
                if (s.key === x) {
                  if (((x = h.type), x === ql)) {
                    if (s.tag === 7) {
                      (a(m, s.sibling), (z = u(s, h.props.children)), (z.return = m), (m = z));
                      break l;
                    }
                  } else if (
                    s.elementType === x ||
                    (typeof x == "object" && x !== null && x.$$typeof === Ql && qa(x) === s.type)
                  ) {
                    (a(m, s.sibling), (z = u(s, h.props)), Ie(z, h), (z.return = m), (m = z));
                    break l;
                  }
                  a(m, s);
                  break;
                } else t(m, s);
                s = s.sibling;
              }
              h.type === ql
                ? ((z = Ha(h.props.children, m.mode, z, h.key)), (z.return = m), (m = z))
                : ((z = wu(h.type, h.key, h.props, null, m.mode, z)),
                  Ie(z, h),
                  (z.return = m),
                  (m = z));
            }
            return i(m);
          case Gl:
            l: {
              for (x = h.key; s !== null;) {
                if (s.key === x)
                  if (
                    s.tag === 4 &&
                    s.stateNode.containerInfo === h.containerInfo &&
                    s.stateNode.implementation === h.implementation
                  ) {
                    (a(m, s.sibling), (z = u(s, h.children || [])), (z.return = m), (m = z));
                    break l;
                  } else {
                    a(m, s);
                    break;
                  }
                else t(m, s);
                s = s.sibling;
              }
              ((z = Di(h, m.mode, z)), (z.return = m), (m = z));
            }
            return i(m);
          case Ql:
            return ((h = qa(h)), cl(m, s, h, z));
        }
        if (bt(h)) return M(m, s, h, z);
        if (Zl(h)) {
          if (((x = Zl(h)), typeof x != "function")) throw Error(d(150));
          return ((h = x.call(h)), C(m, s, h, z));
        }
        if (typeof h.then == "function") return cl(m, s, ln(h), z);
        if (h.$$typeof === xl) return cl(m, s, ku(m, h), z);
        tn(m, h);
      }
      return (typeof h == "string" && h !== "") || typeof h == "number" || typeof h == "bigint"
        ? ((h = "" + h),
          s !== null && s.tag === 6
            ? (a(m, s.sibling), (z = u(s, h)), (z.return = m), (m = z))
            : (a(m, s), (z = Ni(h, m.mode, z)), (z.return = m), (m = z)),
          i(m))
        : a(m, s);
    }
    return function (m, s, h, z) {
      try {
        Fe = 0;
        var x = cl(m, s, h, z);
        return ((ve = null), x);
      } catch (H) {
        if (H === ye || H === Iu) throw H;
        var F = at(29, H, null, m.mode);
        return ((F.lanes = z), (F.return = m), F);
      }
    };
  }
  var Ya = Bs(!0),
    Ys = Bs(!1),
    na = !1;
  function Qi(l) {
    l.updateQueue = {
      baseState: l.memoizedState,
      firstBaseUpdate: null,
      lastBaseUpdate: null,
      shared: { pending: null, lanes: 0, hiddenCallbacks: null },
      callbacks: null,
    };
  }
  function Zi(l, t) {
    ((l = l.updateQueue),
      t.updateQueue === l &&
        (t.updateQueue = {
          baseState: l.baseState,
          firstBaseUpdate: l.firstBaseUpdate,
          lastBaseUpdate: l.lastBaseUpdate,
          shared: l.shared,
          callbacks: null,
        }));
  }
  function ia(l) {
    return { lane: l, tag: 0, payload: null, callback: null, next: null };
  }
  function ca(l, t, a) {
    var e = l.updateQueue;
    if (e === null) return null;
    if (((e = e.shared), (P & 2) !== 0)) {
      var u = e.pending;
      return (
        u === null ? (t.next = t) : ((t.next = u.next), (u.next = t)),
        (e.pending = t),
        (t = Ju(l)),
        _s(l, null, a),
        t
      );
    }
    return (Ku(l, e, t, a), Ju(l));
  }
  function Pe(l, t, a) {
    if (((t = t.updateQueue), t !== null && ((t = t.shared), (a & 4194048) !== 0))) {
      var e = t.lanes;
      ((e &= l.pendingLanes), (a |= e), (t.lanes = a), Df(l, a));
    }
  }
  function Vi(l, t) {
    var a = l.updateQueue,
      e = l.alternate;
    if (e !== null && ((e = e.updateQueue), a === e)) {
      var u = null,
        n = null;
      if (((a = a.firstBaseUpdate), a !== null)) {
        do {
          var i = { lane: a.lane, tag: a.tag, payload: a.payload, callback: null, next: null };
          (n === null ? (u = n = i) : (n = n.next = i), (a = a.next));
        } while (a !== null);
        n === null ? (u = n = t) : (n = n.next = t);
      } else u = n = t;
      ((a = {
        baseState: e.baseState,
        firstBaseUpdate: u,
        lastBaseUpdate: n,
        shared: e.shared,
        callbacks: e.callbacks,
      }),
        (l.updateQueue = a));
      return;
    }
    ((l = a.lastBaseUpdate),
      l === null ? (a.firstBaseUpdate = t) : (l.next = t),
      (a.lastBaseUpdate = t));
  }
  var Li = !1;
  function lu() {
    if (Li) {
      var l = he;
      if (l !== null) throw l;
    }
  }
  function tu(l, t, a, e) {
    Li = !1;
    var u = l.updateQueue;
    na = !1;
    var n = u.firstBaseUpdate,
      i = u.lastBaseUpdate,
      c = u.shared.pending;
    if (c !== null) {
      u.shared.pending = null;
      var f = c,
        y = f.next;
      ((f.next = null), i === null ? (n = y) : (i.next = y), (i = f));
      var g = l.alternate;
      g !== null &&
        ((g = g.updateQueue),
        (c = g.lastBaseUpdate),
        c !== i && (c === null ? (g.firstBaseUpdate = y) : (c.next = y), (g.lastBaseUpdate = f)));
    }
    if (n !== null) {
      var _ = u.baseState;
      ((i = 0), (g = y = f = null), (c = n));
      do {
        var v = c.lane & -536870913,
          r = v !== c.lane;
        if (r ? (w & v) === v : (e & v) === v) {
          (v !== 0 && v === de && (Li = !0),
            g !== null &&
              (g = g.next =
                { lane: 0, tag: c.tag, payload: c.payload, callback: null, next: null }));
          l: {
            var M = l,
              C = c;
            v = t;
            var cl = a;
            switch (C.tag) {
              case 1:
                if (((M = C.payload), typeof M == "function")) {
                  _ = M.call(cl, _, v);
                  break l;
                }
                _ = M;
                break l;
              case 3:
                M.flags = (M.flags & -65537) | 128;
              case 0:
                if (
                  ((M = C.payload), (v = typeof M == "function" ? M.call(cl, _, v) : M), v == null)
                )
                  break l;
                _ = B({}, _, v);
                break l;
              case 2:
                na = !0;
            }
          }
          ((v = c.callback),
            v !== null &&
              ((l.flags |= 64),
              r && (l.flags |= 8192),
              (r = u.callbacks),
              r === null ? (u.callbacks = [v]) : r.push(v)));
        } else
          ((r = { lane: v, tag: c.tag, payload: c.payload, callback: c.callback, next: null }),
            g === null ? ((y = g = r), (f = _)) : (g = g.next = r),
            (i |= v));
        if (((c = c.next), c === null)) {
          if (((c = u.shared.pending), c === null)) break;
          ((r = c),
            (c = r.next),
            (r.next = null),
            (u.lastBaseUpdate = r),
            (u.shared.pending = null));
        }
      } while (!0);
      (g === null && (f = _),
        (u.baseState = f),
        (u.firstBaseUpdate = y),
        (u.lastBaseUpdate = g),
        n === null && (u.shared.lanes = 0),
        (da |= i),
        (l.lanes = i),
        (l.memoizedState = _));
    }
  }
  function Gs(l, t) {
    if (typeof l != "function") throw Error(d(191, l));
    l.call(t);
  }
  function Xs(l, t) {
    var a = l.callbacks;
    if (a !== null) for (l.callbacks = null, l = 0; l < a.length; l++) Gs(a[l], t);
  }
  var re = o(null),
    an = o(0);
  function Qs(l, t) {
    ((l = wt), O(an, l), O(re, t), (wt = l | t.baseLanes));
  }
  function Ki() {
    (O(an, wt), O(re, re.current));
  }
  function Ji() {
    ((wt = an.current), T(re), T(an));
  }
  var et = o(null),
    rt = null;
  function fa(l) {
    var t = l.alternate;
    (O(bl, bl.current & 1),
      O(et, l),
      rt === null && (t === null || re.current !== null || t.memoizedState !== null) && (rt = l));
  }
  function wi(l) {
    (O(bl, bl.current), O(et, l), rt === null && (rt = l));
  }
  function Zs(l) {
    l.tag === 22 ? (O(bl, bl.current), O(et, l), rt === null && (rt = l)) : sa();
  }
  function sa() {
    (O(bl, bl.current), O(et, et.current));
  }
  function ut(l) {
    (T(et), rt === l && (rt = null), T(bl));
  }
  var bl = o(0);
  function en(l) {
    for (var t = l; t !== null;) {
      if (t.tag === 13) {
        var a = t.memoizedState;
        if (a !== null && ((a = a.dehydrated), a === null || Pc(a) || lf(a))) return t;
      } else if (
        t.tag === 19 &&
        (t.memoizedProps.revealOrder === "forwards" ||
          t.memoizedProps.revealOrder === "backwards" ||
          t.memoizedProps.revealOrder === "unstable_legacy-backwards" ||
          t.memoizedProps.revealOrder === "together")
      ) {
        if ((t.flags & 128) !== 0) return t;
      } else if (t.child !== null) {
        ((t.child.return = t), (t = t.child));
        continue;
      }
      if (t === l) break;
      for (; t.sibling === null;) {
        if (t.return === null || t.return === l) return null;
        t = t.return;
      }
      ((t.sibling.return = t.return), (t = t.sibling));
    }
    return null;
  }
  var Gt = 0,
    Q = null,
    nl = null,
    Tl = null,
    un = !1,
    ge = !1,
    Ga = !1,
    nn = 0,
    au = 0,
    Se = null,
    Pd = 0;
  function rl() {
    throw Error(d(321));
  }
  function Wi(l, t) {
    if (t === null) return !1;
    for (var a = 0; a < t.length && a < l.length; a++) if (!tt(l[a], t[a])) return !1;
    return !0;
  }
  function $i(l, t, a, e, u, n) {
    return (
      (Gt = n),
      (Q = t),
      (t.memoizedState = null),
      (t.updateQueue = null),
      (t.lanes = 0),
      (S.H = l === null || l.memoizedState === null ? Oo : oc),
      (Ga = !1),
      (n = a(e, u)),
      (Ga = !1),
      ge && (n = Ls(t, a, e, u)),
      Vs(l),
      n
    );
  }
  function Vs(l) {
    S.H = nu;
    var t = nl !== null && nl.next !== null;
    if (((Gt = 0), (Tl = nl = Q = null), (un = !1), (au = 0), (Se = null), t)) throw Error(d(300));
    l === null || El || ((l = l.dependencies), l !== null && $u(l) && (El = !0));
  }
  function Ls(l, t, a, e) {
    Q = l;
    var u = 0;
    do {
      if ((ge && (Se = null), (au = 0), (ge = !1), 25 <= u)) throw Error(d(301));
      if (((u += 1), (Tl = nl = null), l.updateQueue != null)) {
        var n = l.updateQueue;
        ((n.lastEffect = null),
          (n.events = null),
          (n.stores = null),
          n.memoCache != null && (n.memoCache.index = 0));
      }
      ((S.H = Mo), (n = t(a, e)));
    } while (ge);
    return n;
  }
  function lh() {
    var l = S.H,
      t = l.useState()[0];
    return (
      (t = typeof t.then == "function" ? eu(t) : t),
      (l = l.useState()[0]),
      (nl !== null ? nl.memoizedState : null) !== l && (Q.flags |= 1024),
      t
    );
  }
  function ki() {
    var l = nn !== 0;
    return ((nn = 0), l);
  }
  function Fi(l, t, a) {
    ((t.updateQueue = l.updateQueue), (t.flags &= -2053), (l.lanes &= ~a));
  }
  function Ii(l) {
    if (un) {
      for (l = l.memoizedState; l !== null;) {
        var t = l.queue;
        (t !== null && (t.pending = null), (l = l.next));
      }
      un = !1;
    }
    ((Gt = 0), (Tl = nl = Q = null), (ge = !1), (au = nn = 0), (Se = null));
  }
  function Yl() {
    var l = { memoizedState: null, baseState: null, baseQueue: null, queue: null, next: null };
    return (Tl === null ? (Q.memoizedState = Tl = l) : (Tl = Tl.next = l), Tl);
  }
  function zl() {
    if (nl === null) {
      var l = Q.alternate;
      l = l !== null ? l.memoizedState : null;
    } else l = nl.next;
    var t = Tl === null ? Q.memoizedState : Tl.next;
    if (t !== null) ((Tl = t), (nl = l));
    else {
      if (l === null) throw Q.alternate === null ? Error(d(467)) : Error(d(310));
      ((nl = l),
        (l = {
          memoizedState: nl.memoizedState,
          baseState: nl.baseState,
          baseQueue: nl.baseQueue,
          queue: nl.queue,
          next: null,
        }),
        Tl === null ? (Q.memoizedState = Tl = l) : (Tl = Tl.next = l));
    }
    return Tl;
  }
  function cn() {
    return { lastEffect: null, events: null, stores: null, memoCache: null };
  }
  function eu(l) {
    var t = au;
    return (
      (au += 1),
      Se === null && (Se = []),
      (l = xs(Se, l, t)),
      (t = Q),
      (Tl === null ? t.memoizedState : Tl.next) === null &&
        ((t = t.alternate), (S.H = t === null || t.memoizedState === null ? Oo : oc)),
      l
    );
  }
  function fn(l) {
    if (l !== null && typeof l == "object") {
      if (typeof l.then == "function") return eu(l);
      if (l.$$typeof === xl) return Hl(l);
    }
    throw Error(d(438, String(l)));
  }
  function Pi(l) {
    var t = null,
      a = Q.updateQueue;
    if ((a !== null && (t = a.memoCache), t == null)) {
      var e = Q.alternate;
      e !== null &&
        ((e = e.updateQueue),
        e !== null &&
          ((e = e.memoCache),
          e != null &&
            (t = {
              data: e.data.map(function (u) {
                return u.slice();
              }),
              index: 0,
            })));
    }
    if (
      (t == null && (t = { data: [], index: 0 }),
      a === null && ((a = cn()), (Q.updateQueue = a)),
      (a.memoCache = t),
      (a = t.data[t.index]),
      a === void 0)
    )
      for (a = t.data[t.index] = Array(l), e = 0; e < l; e++) a[e] = wa;
    return (t.index++, a);
  }
  function Xt(l, t) {
    return typeof t == "function" ? t(l) : t;
  }
  function sn(l) {
    var t = zl();
    return lc(t, nl, l);
  }
  function lc(l, t, a) {
    var e = l.queue;
    if (e === null) throw Error(d(311));
    e.lastRenderedReducer = a;
    var u = l.baseQueue,
      n = e.pending;
    if (n !== null) {
      if (u !== null) {
        var i = u.next;
        ((u.next = n.next), (n.next = i));
      }
      ((t.baseQueue = u = n), (e.pending = null));
    }
    if (((n = l.baseState), u === null)) l.memoizedState = n;
    else {
      t = u.next;
      var c = (i = null),
        f = null,
        y = t,
        g = !1;
      do {
        var _ = y.lane & -536870913;
        if (_ !== y.lane ? (w & _) === _ : (Gt & _) === _) {
          var v = y.revertLane;
          if (v === 0)
            (f !== null &&
              (f = f.next =
                {
                  lane: 0,
                  revertLane: 0,
                  gesture: null,
                  action: y.action,
                  hasEagerState: y.hasEagerState,
                  eagerState: y.eagerState,
                  next: null,
                }),
              _ === de && (g = !0));
          else if ((Gt & v) === v) {
            ((y = y.next), v === de && (g = !0));
            continue;
          } else
            ((_ = {
              lane: 0,
              revertLane: y.revertLane,
              gesture: null,
              action: y.action,
              hasEagerState: y.hasEagerState,
              eagerState: y.eagerState,
              next: null,
            }),
              f === null ? ((c = f = _), (i = n)) : (f = f.next = _),
              (Q.lanes |= v),
              (da |= v));
          ((_ = y.action), Ga && a(n, _), (n = y.hasEagerState ? y.eagerState : a(n, _)));
        } else
          ((v = {
            lane: _,
            revertLane: y.revertLane,
            gesture: y.gesture,
            action: y.action,
            hasEagerState: y.hasEagerState,
            eagerState: y.eagerState,
            next: null,
          }),
            f === null ? ((c = f = v), (i = n)) : (f = f.next = v),
            (Q.lanes |= _),
            (da |= _));
        y = y.next;
      } while (y !== null && y !== t);
      if (
        (f === null ? (i = n) : (f.next = c),
        !tt(n, l.memoizedState) && ((El = !0), g && ((a = he), a !== null)))
      )
        throw a;
      ((l.memoizedState = n), (l.baseState = i), (l.baseQueue = f), (e.lastRenderedState = n));
    }
    return (u === null && (e.lanes = 0), [l.memoizedState, e.dispatch]);
  }
  function tc(l) {
    var t = zl(),
      a = t.queue;
    if (a === null) throw Error(d(311));
    a.lastRenderedReducer = l;
    var e = a.dispatch,
      u = a.pending,
      n = t.memoizedState;
    if (u !== null) {
      a.pending = null;
      var i = (u = u.next);
      do ((n = l(n, i.action)), (i = i.next));
      while (i !== u);
      (tt(n, t.memoizedState) || (El = !0),
        (t.memoizedState = n),
        t.baseQueue === null && (t.baseState = n),
        (a.lastRenderedState = n));
    }
    return [n, e];
  }
  function Ks(l, t, a) {
    var e = Q,
      u = zl(),
      n = k;
    if (n) {
      if (a === void 0) throw Error(d(407));
      a = a();
    } else a = t();
    var i = !tt((nl || u).memoizedState, a);
    if (
      (i && ((u.memoizedState = a), (El = !0)),
      (u = u.queue),
      uc(Ws.bind(null, e, u, l), [l]),
      u.getSnapshot !== t || i || (Tl !== null && Tl.memoizedState.tag & 1))
    ) {
      if (
        ((e.flags |= 2048),
        be(9, { destroy: void 0 }, ws.bind(null, e, u, a, t), null),
        sl === null)
      )
        throw Error(d(349));
      n || (Gt & 127) !== 0 || Js(e, t, a);
    }
    return a;
  }
  function Js(l, t, a) {
    ((l.flags |= 16384),
      (l = { getSnapshot: t, value: a }),
      (t = Q.updateQueue),
      t === null
        ? ((t = cn()), (Q.updateQueue = t), (t.stores = [l]))
        : ((a = t.stores), a === null ? (t.stores = [l]) : a.push(l)));
  }
  function ws(l, t, a, e) {
    ((t.value = a), (t.getSnapshot = e), $s(t) && ks(l));
  }
  function Ws(l, t, a) {
    return a(function () {
      $s(t) && ks(l);
    });
  }
  function $s(l) {
    var t = l.getSnapshot;
    l = l.value;
    try {
      var a = t();
      return !tt(l, a);
    } catch {
      return !0;
    }
  }
  function ks(l) {
    var t = Ua(l, 2);
    t !== null && $l(t, l, 2);
  }
  function ac(l) {
    var t = Yl();
    if (typeof l == "function") {
      var a = l;
      if (((l = a()), Ga)) {
        It(!0);
        try {
          a();
        } finally {
          It(!1);
        }
      }
    }
    return (
      (t.memoizedState = t.baseState = l),
      (t.queue = {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: Xt,
        lastRenderedState: l,
      }),
      t
    );
  }
  function Fs(l, t, a, e) {
    return ((l.baseState = a), lc(l, nl, typeof e == "function" ? e : Xt));
  }
  function th(l, t, a, e, u) {
    if (dn(l)) throw Error(d(485));
    if (((l = t.action), l !== null)) {
      var n = {
        payload: u,
        action: l,
        next: null,
        isTransition: !0,
        status: "pending",
        value: null,
        reason: null,
        listeners: [],
        then: function (i) {
          n.listeners.push(i);
        },
      };
      (S.T !== null ? a(!0) : (n.isTransition = !1),
        e(n),
        (a = t.pending),
        a === null
          ? ((n.next = t.pending = n), Is(t, n))
          : ((n.next = a.next), (t.pending = a.next = n)));
    }
  }
  function Is(l, t) {
    var a = t.action,
      e = t.payload,
      u = l.state;
    if (t.isTransition) {
      var n = S.T,
        i = {};
      S.T = i;
      try {
        var c = a(u, e),
          f = S.S;
        (f !== null && f(i, c), Ps(l, t, c));
      } catch (y) {
        ec(l, t, y);
      } finally {
        (n !== null && i.types !== null && (n.types = i.types), (S.T = n));
      }
    } else
      try {
        ((n = a(u, e)), Ps(l, t, n));
      } catch (y) {
        ec(l, t, y);
      }
  }
  function Ps(l, t, a) {
    a !== null && typeof a == "object" && typeof a.then == "function"
      ? a.then(
          function (e) {
            lo(l, t, e);
          },
          function (e) {
            return ec(l, t, e);
          },
        )
      : lo(l, t, a);
  }
  function lo(l, t, a) {
    ((t.status = "fulfilled"),
      (t.value = a),
      to(t),
      (l.state = a),
      (t = l.pending),
      t !== null &&
        ((a = t.next), a === t ? (l.pending = null) : ((a = a.next), (t.next = a), Is(l, a))));
  }
  function ec(l, t, a) {
    var e = l.pending;
    if (((l.pending = null), e !== null)) {
      e = e.next;
      do ((t.status = "rejected"), (t.reason = a), to(t), (t = t.next));
      while (t !== e);
    }
    l.action = null;
  }
  function to(l) {
    l = l.listeners;
    for (var t = 0; t < l.length; t++) (0, l[t])();
  }
  function ao(l, t) {
    return t;
  }
  function eo(l, t) {
    if (k) {
      var a = sl.formState;
      if (a !== null) {
        l: {
          var e = Q;
          if (k) {
            if (ol) {
              t: {
                for (var u = ol, n = vt; u.nodeType !== 8;) {
                  if (!n) {
                    u = null;
                    break t;
                  }
                  if (((u = gt(u.nextSibling)), u === null)) {
                    u = null;
                    break t;
                  }
                }
                ((n = u.data), (u = n === "F!" || n === "F" ? u : null));
              }
              if (u) {
                ((ol = gt(u.nextSibling)), (e = u.data === "F!"));
                break l;
              }
            }
            ea(e);
          }
          e = !1;
        }
        e && (t = a[0]);
      }
    }
    return (
      (a = Yl()),
      (a.memoizedState = a.baseState = t),
      (e = {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: ao,
        lastRenderedState: t,
      }),
      (a.queue = e),
      (a = Eo.bind(null, Q, e)),
      (e.dispatch = a),
      (e = ac(!1)),
      (n = sc.bind(null, Q, !1, e.queue)),
      (e = Yl()),
      (u = { state: t, dispatch: null, action: l, pending: null }),
      (e.queue = u),
      (a = th.bind(null, Q, u, n, a)),
      (u.dispatch = a),
      (e.memoizedState = l),
      [t, a, !1]
    );
  }
  function uo(l) {
    var t = zl();
    return no(t, nl, l);
  }
  function no(l, t, a) {
    if (
      ((t = lc(l, t, ao)[0]),
      (l = sn(Xt)[0]),
      typeof t == "object" && t !== null && typeof t.then == "function")
    )
      try {
        var e = eu(t);
      } catch (i) {
        throw i === ye ? Iu : i;
      }
    else e = t;
    t = zl();
    var u = t.queue,
      n = u.dispatch;
    return (
      a !== t.memoizedState &&
        ((Q.flags |= 2048), be(9, { destroy: void 0 }, ah.bind(null, u, a), null)),
      [e, n, l]
    );
  }
  function ah(l, t) {
    l.action = t;
  }
  function io(l) {
    var t = zl(),
      a = nl;
    if (a !== null) return no(t, a, l);
    (zl(), (t = t.memoizedState), (a = zl()));
    var e = a.queue.dispatch;
    return ((a.memoizedState = l), [t, e, !1]);
  }
  function be(l, t, a, e) {
    return (
      (l = { tag: l, create: a, deps: e, inst: t, next: null }),
      (t = Q.updateQueue),
      t === null && ((t = cn()), (Q.updateQueue = t)),
      (a = t.lastEffect),
      a === null
        ? (t.lastEffect = l.next = l)
        : ((e = a.next), (a.next = l), (l.next = e), (t.lastEffect = l)),
      l
    );
  }
  function co() {
    return zl().memoizedState;
  }
  function on(l, t, a, e) {
    var u = Yl();
    ((Q.flags |= l),
      (u.memoizedState = be(1 | t, { destroy: void 0 }, a, e === void 0 ? null : e)));
  }
  function mn(l, t, a, e) {
    var u = zl();
    e = e === void 0 ? null : e;
    var n = u.memoizedState.inst;
    nl !== null && e !== null && Wi(e, nl.memoizedState.deps)
      ? (u.memoizedState = be(t, n, a, e))
      : ((Q.flags |= l), (u.memoizedState = be(1 | t, n, a, e)));
  }
  function fo(l, t) {
    on(8390656, 8, l, t);
  }
  function uc(l, t) {
    mn(2048, 8, l, t);
  }
  function eh(l) {
    Q.flags |= 4;
    var t = Q.updateQueue;
    if (t === null) ((t = cn()), (Q.updateQueue = t), (t.events = [l]));
    else {
      var a = t.events;
      a === null ? (t.events = [l]) : a.push(l);
    }
  }
  function so(l) {
    var t = zl().memoizedState;
    return (
      eh({ ref: t, nextImpl: l }),
      function () {
        if ((P & 2) !== 0) throw Error(d(440));
        return t.impl.apply(void 0, arguments);
      }
    );
  }
  function oo(l, t) {
    return mn(4, 2, l, t);
  }
  function mo(l, t) {
    return mn(4, 4, l, t);
  }
  function ho(l, t) {
    if (typeof t == "function") {
      l = l();
      var a = t(l);
      return function () {
        typeof a == "function" ? a() : t(null);
      };
    }
    if (t != null)
      return (
        (l = l()),
        (t.current = l),
        function () {
          t.current = null;
        }
      );
  }
  function yo(l, t, a) {
    ((a = a != null ? a.concat([l]) : null), mn(4, 4, ho.bind(null, t, l), a));
  }
  function nc() {}
  function vo(l, t) {
    var a = zl();
    t = t === void 0 ? null : t;
    var e = a.memoizedState;
    return t !== null && Wi(t, e[1]) ? e[0] : ((a.memoizedState = [l, t]), l);
  }
  function ro(l, t) {
    var a = zl();
    t = t === void 0 ? null : t;
    var e = a.memoizedState;
    if (t !== null && Wi(t, e[1])) return e[0];
    if (((e = l()), Ga)) {
      It(!0);
      try {
        l();
      } finally {
        It(!1);
      }
    }
    return ((a.memoizedState = [e, t]), e);
  }
  function ic(l, t, a) {
    return a === void 0 || ((Gt & 1073741824) !== 0 && (w & 261930) === 0)
      ? (l.memoizedState = t)
      : ((l.memoizedState = a), (l = g0()), (Q.lanes |= l), (da |= l), a);
  }
  function go(l, t, a, e) {
    return tt(a, t)
      ? a
      : re.current !== null
        ? ((l = ic(l, a, e)), tt(l, t) || (El = !0), l)
        : (Gt & 42) === 0 || ((Gt & 1073741824) !== 0 && (w & 261930) === 0)
          ? ((El = !0), (l.memoizedState = a))
          : ((l = g0()), (Q.lanes |= l), (da |= l), t);
  }
  function So(l, t, a, e, u) {
    var n = p.p;
    p.p = n !== 0 && 8 > n ? n : 8;
    var i = S.T,
      c = {};
    ((S.T = c), sc(l, !1, t, a));
    try {
      var f = u(),
        y = S.S;
      if (
        (y !== null && y(c, f), f !== null && typeof f == "object" && typeof f.then == "function")
      ) {
        var g = Id(f, e);
        uu(l, t, g, ct(l));
      } else uu(l, t, e, ct(l));
    } catch (_) {
      uu(l, t, { then: function () {}, status: "rejected", reason: _ }, ct());
    } finally {
      ((p.p = n), i !== null && c.types !== null && (i.types = c.types), (S.T = i));
    }
  }
  function uh() {}
  function cc(l, t, a, e) {
    if (l.tag !== 5) throw Error(d(476));
    var u = bo(l).queue;
    So(
      l,
      u,
      t,
      Y,
      a === null
        ? uh
        : function () {
            return (zo(l), a(e));
          },
    );
  }
  function bo(l) {
    var t = l.memoizedState;
    if (t !== null) return t;
    t = {
      memoizedState: Y,
      baseState: Y,
      baseQueue: null,
      queue: {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: Xt,
        lastRenderedState: Y,
      },
      next: null,
    };
    var a = {};
    return (
      (t.next = {
        memoizedState: a,
        baseState: a,
        baseQueue: null,
        queue: {
          pending: null,
          lanes: 0,
          dispatch: null,
          lastRenderedReducer: Xt,
          lastRenderedState: a,
        },
        next: null,
      }),
      (l.memoizedState = t),
      (l = l.alternate),
      l !== null && (l.memoizedState = t),
      t
    );
  }
  function zo(l) {
    var t = bo(l);
    (t.next === null && (t = l.alternate.memoizedState), uu(l, t.next.queue, {}, ct()));
  }
  function fc() {
    return Hl(_u);
  }
  function _o() {
    return zl().memoizedState;
  }
  function To() {
    return zl().memoizedState;
  }
  function nh(l) {
    for (var t = l.return; t !== null;) {
      switch (t.tag) {
        case 24:
        case 3:
          var a = ct();
          l = ia(a);
          var e = ca(t, l, a);
          (e !== null && ($l(e, t, a), Pe(e, t, a)), (t = { cache: Bi() }), (l.payload = t));
          return;
      }
      t = t.return;
    }
  }
  function ih(l, t, a) {
    var e = ct();
    ((a = {
      lane: e,
      revertLane: 0,
      gesture: null,
      action: a,
      hasEagerState: !1,
      eagerState: null,
      next: null,
    }),
      dn(l) ? Ao(t, a) : ((a = Oi(l, t, a, e)), a !== null && ($l(a, l, e), po(a, t, e))));
  }
  function Eo(l, t, a) {
    var e = ct();
    uu(l, t, a, e);
  }
  function uu(l, t, a, e) {
    var u = {
      lane: e,
      revertLane: 0,
      gesture: null,
      action: a,
      hasEagerState: !1,
      eagerState: null,
      next: null,
    };
    if (dn(l)) Ao(t, u);
    else {
      var n = l.alternate;
      if (
        l.lanes === 0 &&
        (n === null || n.lanes === 0) &&
        ((n = t.lastRenderedReducer), n !== null)
      )
        try {
          var i = t.lastRenderedState,
            c = n(i, a);
          if (((u.hasEagerState = !0), (u.eagerState = c), tt(c, i)))
            return (Ku(l, t, u, 0), sl === null && Lu(), !1);
        } catch {}
      if (((a = Oi(l, t, u, e)), a !== null)) return ($l(a, l, e), po(a, t, e), !0);
    }
    return !1;
  }
  function sc(l, t, a, e) {
    if (
      ((e = {
        lane: 2,
        revertLane: Qc(),
        gesture: null,
        action: e,
        hasEagerState: !1,
        eagerState: null,
        next: null,
      }),
      dn(l))
    ) {
      if (t) throw Error(d(479));
    } else ((t = Oi(l, a, e, 2)), t !== null && $l(t, l, 2));
  }
  function dn(l) {
    var t = l.alternate;
    return l === Q || (t !== null && t === Q);
  }
  function Ao(l, t) {
    ge = un = !0;
    var a = l.pending;
    (a === null ? (t.next = t) : ((t.next = a.next), (a.next = t)), (l.pending = t));
  }
  function po(l, t, a) {
    if ((a & 4194048) !== 0) {
      var e = t.lanes;
      ((e &= l.pendingLanes), (a |= e), (t.lanes = a), Df(l, a));
    }
  }
  var nu = {
    readContext: Hl,
    use: fn,
    useCallback: rl,
    useContext: rl,
    useEffect: rl,
    useImperativeHandle: rl,
    useLayoutEffect: rl,
    useInsertionEffect: rl,
    useMemo: rl,
    useReducer: rl,
    useRef: rl,
    useState: rl,
    useDebugValue: rl,
    useDeferredValue: rl,
    useTransition: rl,
    useSyncExternalStore: rl,
    useId: rl,
    useHostTransitionStatus: rl,
    useFormState: rl,
    useActionState: rl,
    useOptimistic: rl,
    useMemoCache: rl,
    useCacheRefresh: rl,
  };
  nu.useEffectEvent = rl;
  var Oo = {
      readContext: Hl,
      use: fn,
      useCallback: function (l, t) {
        return ((Yl().memoizedState = [l, t === void 0 ? null : t]), l);
      },
      useContext: Hl,
      useEffect: fo,
      useImperativeHandle: function (l, t, a) {
        ((a = a != null ? a.concat([l]) : null), on(4194308, 4, ho.bind(null, t, l), a));
      },
      useLayoutEffect: function (l, t) {
        return on(4194308, 4, l, t);
      },
      useInsertionEffect: function (l, t) {
        on(4, 2, l, t);
      },
      useMemo: function (l, t) {
        var a = Yl();
        t = t === void 0 ? null : t;
        var e = l();
        if (Ga) {
          It(!0);
          try {
            l();
          } finally {
            It(!1);
          }
        }
        return ((a.memoizedState = [e, t]), e);
      },
      useReducer: function (l, t, a) {
        var e = Yl();
        if (a !== void 0) {
          var u = a(t);
          if (Ga) {
            It(!0);
            try {
              a(t);
            } finally {
              It(!1);
            }
          }
        } else u = t;
        return (
          (e.memoizedState = e.baseState = u),
          (l = {
            pending: null,
            lanes: 0,
            dispatch: null,
            lastRenderedReducer: l,
            lastRenderedState: u,
          }),
          (e.queue = l),
          (l = l.dispatch = ih.bind(null, Q, l)),
          [e.memoizedState, l]
        );
      },
      useRef: function (l) {
        var t = Yl();
        return ((l = { current: l }), (t.memoizedState = l));
      },
      useState: function (l) {
        l = ac(l);
        var t = l.queue,
          a = Eo.bind(null, Q, t);
        return ((t.dispatch = a), [l.memoizedState, a]);
      },
      useDebugValue: nc,
      useDeferredValue: function (l, t) {
        var a = Yl();
        return ic(a, l, t);
      },
      useTransition: function () {
        var l = ac(!1);
        return ((l = So.bind(null, Q, l.queue, !0, !1)), (Yl().memoizedState = l), [!1, l]);
      },
      useSyncExternalStore: function (l, t, a) {
        var e = Q,
          u = Yl();
        if (k) {
          if (a === void 0) throw Error(d(407));
          a = a();
        } else {
          if (((a = t()), sl === null)) throw Error(d(349));
          (w & 127) !== 0 || Js(e, t, a);
        }
        u.memoizedState = a;
        var n = { value: a, getSnapshot: t };
        return (
          (u.queue = n),
          fo(Ws.bind(null, e, n, l), [l]),
          (e.flags |= 2048),
          be(9, { destroy: void 0 }, ws.bind(null, e, n, a, t), null),
          a
        );
      },
      useId: function () {
        var l = Yl(),
          t = sl.identifierPrefix;
        if (k) {
          var a = Mt,
            e = Ot;
          ((a = (e & ~(1 << (32 - lt(e) - 1))).toString(32) + a),
            (t = "_" + t + "R_" + a),
            (a = nn++),
            0 < a && (t += "H" + a.toString(32)),
            (t += "_"));
        } else ((a = Pd++), (t = "_" + t + "r_" + a.toString(32) + "_"));
        return (l.memoizedState = t);
      },
      useHostTransitionStatus: fc,
      useFormState: eo,
      useActionState: eo,
      useOptimistic: function (l) {
        var t = Yl();
        t.memoizedState = t.baseState = l;
        var a = {
          pending: null,
          lanes: 0,
          dispatch: null,
          lastRenderedReducer: null,
          lastRenderedState: null,
        };
        return ((t.queue = a), (t = sc.bind(null, Q, !0, a)), (a.dispatch = t), [l, t]);
      },
      useMemoCache: Pi,
      useCacheRefresh: function () {
        return (Yl().memoizedState = nh.bind(null, Q));
      },
      useEffectEvent: function (l) {
        var t = Yl(),
          a = { impl: l };
        return (
          (t.memoizedState = a),
          function () {
            if ((P & 2) !== 0) throw Error(d(440));
            return a.impl.apply(void 0, arguments);
          }
        );
      },
    },
    oc = {
      readContext: Hl,
      use: fn,
      useCallback: vo,
      useContext: Hl,
      useEffect: uc,
      useImperativeHandle: yo,
      useInsertionEffect: oo,
      useLayoutEffect: mo,
      useMemo: ro,
      useReducer: sn,
      useRef: co,
      useState: function () {
        return sn(Xt);
      },
      useDebugValue: nc,
      useDeferredValue: function (l, t) {
        var a = zl();
        return go(a, nl.memoizedState, l, t);
      },
      useTransition: function () {
        var l = sn(Xt)[0],
          t = zl().memoizedState;
        return [typeof l == "boolean" ? l : eu(l), t];
      },
      useSyncExternalStore: Ks,
      useId: _o,
      useHostTransitionStatus: fc,
      useFormState: uo,
      useActionState: uo,
      useOptimistic: function (l, t) {
        var a = zl();
        return Fs(a, nl, l, t);
      },
      useMemoCache: Pi,
      useCacheRefresh: To,
    };
  oc.useEffectEvent = so;
  var Mo = {
    readContext: Hl,
    use: fn,
    useCallback: vo,
    useContext: Hl,
    useEffect: uc,
    useImperativeHandle: yo,
    useInsertionEffect: oo,
    useLayoutEffect: mo,
    useMemo: ro,
    useReducer: tc,
    useRef: co,
    useState: function () {
      return tc(Xt);
    },
    useDebugValue: nc,
    useDeferredValue: function (l, t) {
      var a = zl();
      return nl === null ? ic(a, l, t) : go(a, nl.memoizedState, l, t);
    },
    useTransition: function () {
      var l = tc(Xt)[0],
        t = zl().memoizedState;
      return [typeof l == "boolean" ? l : eu(l), t];
    },
    useSyncExternalStore: Ks,
    useId: _o,
    useHostTransitionStatus: fc,
    useFormState: io,
    useActionState: io,
    useOptimistic: function (l, t) {
      var a = zl();
      return nl !== null ? Fs(a, nl, l, t) : ((a.baseState = l), [l, a.queue.dispatch]);
    },
    useMemoCache: Pi,
    useCacheRefresh: To,
  };
  Mo.useEffectEvent = so;
  function mc(l, t, a, e) {
    ((t = l.memoizedState),
      (a = a(e, t)),
      (a = a == null ? t : B({}, t, a)),
      (l.memoizedState = a),
      l.lanes === 0 && (l.updateQueue.baseState = a));
  }
  var dc = {
    enqueueSetState: function (l, t, a) {
      l = l._reactInternals;
      var e = ct(),
        u = ia(e);
      ((u.payload = t),
        a != null && (u.callback = a),
        (t = ca(l, u, e)),
        t !== null && ($l(t, l, e), Pe(t, l, e)));
    },
    enqueueReplaceState: function (l, t, a) {
      l = l._reactInternals;
      var e = ct(),
        u = ia(e);
      ((u.tag = 1),
        (u.payload = t),
        a != null && (u.callback = a),
        (t = ca(l, u, e)),
        t !== null && ($l(t, l, e), Pe(t, l, e)));
    },
    enqueueForceUpdate: function (l, t) {
      l = l._reactInternals;
      var a = ct(),
        e = ia(a);
      ((e.tag = 2),
        t != null && (e.callback = t),
        (t = ca(l, e, a)),
        t !== null && ($l(t, l, a), Pe(t, l, a)));
    },
  };
  function No(l, t, a, e, u, n, i) {
    return (
      (l = l.stateNode),
      typeof l.shouldComponentUpdate == "function"
        ? l.shouldComponentUpdate(e, n, i)
        : t.prototype && t.prototype.isPureReactComponent
          ? !Ke(a, e) || !Ke(u, n)
          : !0
    );
  }
  function Do(l, t, a, e) {
    ((l = t.state),
      typeof t.componentWillReceiveProps == "function" && t.componentWillReceiveProps(a, e),
      typeof t.UNSAFE_componentWillReceiveProps == "function" &&
        t.UNSAFE_componentWillReceiveProps(a, e),
      t.state !== l && dc.enqueueReplaceState(t, t.state, null));
  }
  function Xa(l, t) {
    var a = t;
    if ("ref" in t) {
      a = {};
      for (var e in t) e !== "ref" && (a[e] = t[e]);
    }
    if ((l = l.defaultProps)) {
      a === t && (a = B({}, a));
      for (var u in l) a[u] === void 0 && (a[u] = l[u]);
    }
    return a;
  }
  function Uo(l) {
    Vu(l);
  }
  function Ho(l) {
    console.error(l);
  }
  function jo(l) {
    Vu(l);
  }
  function hn(l, t) {
    try {
      var a = l.onUncaughtError;
      a(t.value, { componentStack: t.stack });
    } catch (e) {
      setTimeout(function () {
        throw e;
      });
    }
  }
  function Ro(l, t, a) {
    try {
      var e = l.onCaughtError;
      e(a.value, { componentStack: a.stack, errorBoundary: t.tag === 1 ? t.stateNode : null });
    } catch (u) {
      setTimeout(function () {
        throw u;
      });
    }
  }
  function hc(l, t, a) {
    return (
      (a = ia(a)),
      (a.tag = 3),
      (a.payload = { element: null }),
      (a.callback = function () {
        hn(l, t);
      }),
      a
    );
  }
  function xo(l) {
    return ((l = ia(l)), (l.tag = 3), l);
  }
  function Co(l, t, a, e) {
    var u = a.type.getDerivedStateFromError;
    if (typeof u == "function") {
      var n = e.value;
      ((l.payload = function () {
        return u(n);
      }),
        (l.callback = function () {
          Ro(t, a, e);
        }));
    }
    var i = a.stateNode;
    i !== null &&
      typeof i.componentDidCatch == "function" &&
      (l.callback = function () {
        (Ro(t, a, e),
          typeof u != "function" && (ha === null ? (ha = new Set([this])) : ha.add(this)));
        var c = e.stack;
        this.componentDidCatch(e.value, { componentStack: c !== null ? c : "" });
      });
  }
  function ch(l, t, a, e, u) {
    if (((a.flags |= 32768), e !== null && typeof e == "object" && typeof e.then == "function")) {
      if (((t = a.alternate), t !== null && me(t, a, u, !0), (a = et.current), a !== null)) {
        switch (a.tag) {
          case 31:
          case 13:
            return (
              rt === null ? pn() : a.alternate === null && gl === 0 && (gl = 3),
              (a.flags &= -257),
              (a.flags |= 65536),
              (a.lanes = u),
              e === Pu
                ? (a.flags |= 16384)
                : ((t = a.updateQueue),
                  t === null ? (a.updateQueue = new Set([e])) : t.add(e),
                  Yc(l, e, u)),
              !1
            );
          case 22:
            return (
              (a.flags |= 65536),
              e === Pu
                ? (a.flags |= 16384)
                : ((t = a.updateQueue),
                  t === null
                    ? ((t = { transitions: null, markerInstances: null, retryQueue: new Set([e]) }),
                      (a.updateQueue = t))
                    : ((a = t.retryQueue), a === null ? (t.retryQueue = new Set([e])) : a.add(e)),
                  Yc(l, e, u)),
              !1
            );
        }
        throw Error(d(435, a.tag));
      }
      return (Yc(l, e, u), pn(), !1);
    }
    if (k)
      return (
        (t = et.current),
        t !== null
          ? ((t.flags & 65536) === 0 && (t.flags |= 256),
            (t.flags |= 65536),
            (t.lanes = u),
            e !== ji && ((l = Error(d(422), { cause: e })), We(dt(l, a))))
          : (e !== ji && ((t = Error(d(423), { cause: e })), We(dt(t, a))),
            (l = l.current.alternate),
            (l.flags |= 65536),
            (u &= -u),
            (l.lanes |= u),
            (e = dt(e, a)),
            (u = hc(l.stateNode, e, u)),
            Vi(l, u),
            gl !== 4 && (gl = 2)),
        !1
      );
    var n = Error(d(520), { cause: e });
    if (((n = dt(n, a)), hu === null ? (hu = [n]) : hu.push(n), gl !== 4 && (gl = 2), t === null))
      return !0;
    ((e = dt(e, a)), (a = t));
    do {
      switch (a.tag) {
        case 3:
          return (
            (a.flags |= 65536),
            (l = u & -u),
            (a.lanes |= l),
            (l = hc(a.stateNode, e, l)),
            Vi(a, l),
            !1
          );
        case 1:
          if (
            ((t = a.type),
            (n = a.stateNode),
            (a.flags & 128) === 0 &&
              (typeof t.getDerivedStateFromError == "function" ||
                (n !== null &&
                  typeof n.componentDidCatch == "function" &&
                  (ha === null || !ha.has(n)))))
          )
            return (
              (a.flags |= 65536),
              (u &= -u),
              (a.lanes |= u),
              (u = xo(u)),
              Co(u, l, a, e),
              Vi(a, u),
              !1
            );
      }
      a = a.return;
    } while (a !== null);
    return !1;
  }
  var yc = Error(d(461)),
    El = !1;
  function jl(l, t, a, e) {
    t.child = l === null ? Ys(t, null, a, e) : Ya(t, l.child, a, e);
  }
  function qo(l, t, a, e, u) {
    a = a.render;
    var n = t.ref;
    if ("ref" in e) {
      var i = {};
      for (var c in e) c !== "ref" && (i[c] = e[c]);
    } else i = e;
    return (
      xa(t),
      (e = $i(l, t, a, i, n, u)),
      (c = ki()),
      l !== null && !El
        ? (Fi(l, t, u), Qt(l, t, u))
        : (k && c && Ui(t), (t.flags |= 1), jl(l, t, e, u), t.child)
    );
  }
  function Bo(l, t, a, e, u) {
    if (l === null) {
      var n = a.type;
      return typeof n == "function" && !Mi(n) && n.defaultProps === void 0 && a.compare === null
        ? ((t.tag = 15), (t.type = n), Yo(l, t, n, e, u))
        : ((l = wu(a.type, null, e, t, t.mode, u)), (l.ref = t.ref), (l.return = t), (t.child = l));
    }
    if (((n = l.child), !Tc(l, u))) {
      var i = n.memoizedProps;
      if (((a = a.compare), (a = a !== null ? a : Ke), a(i, e) && l.ref === t.ref))
        return Qt(l, t, u);
    }
    return ((t.flags |= 1), (l = Ct(n, e)), (l.ref = t.ref), (l.return = t), (t.child = l));
  }
  function Yo(l, t, a, e, u) {
    if (l !== null) {
      var n = l.memoizedProps;
      if (Ke(n, e) && l.ref === t.ref)
        if (((El = !1), (t.pendingProps = e = n), Tc(l, u))) (l.flags & 131072) !== 0 && (El = !0);
        else return ((t.lanes = l.lanes), Qt(l, t, u));
    }
    return vc(l, t, a, e, u);
  }
  function Go(l, t, a, e) {
    var u = e.children,
      n = l !== null ? l.memoizedState : null;
    if (
      (l === null &&
        t.stateNode === null &&
        (t.stateNode = {
          _visibility: 1,
          _pendingMarkers: null,
          _retryCache: null,
          _transitions: null,
        }),
      e.mode === "hidden")
    ) {
      if ((t.flags & 128) !== 0) {
        if (((n = n !== null ? n.baseLanes | a : a), l !== null)) {
          for (e = t.child = l.child, u = 0; e !== null;)
            ((u = u | e.lanes | e.childLanes), (e = e.sibling));
          e = u & ~n;
        } else ((e = 0), (t.child = null));
        return Xo(l, t, n, a, e);
      }
      if ((a & 536870912) !== 0)
        ((t.memoizedState = { baseLanes: 0, cachePool: null }),
          l !== null && Fu(t, n !== null ? n.cachePool : null),
          n !== null ? Qs(t, n) : Ki(),
          Zs(t));
      else return ((e = t.lanes = 536870912), Xo(l, t, n !== null ? n.baseLanes | a : a, a, e));
    } else
      n !== null
        ? (Fu(t, n.cachePool), Qs(t, n), sa(), (t.memoizedState = null))
        : (l !== null && Fu(t, null), Ki(), sa());
    return (jl(l, t, u, a), t.child);
  }
  function iu(l, t) {
    return (
      (l !== null && l.tag === 22) ||
        t.stateNode !== null ||
        (t.stateNode = {
          _visibility: 1,
          _pendingMarkers: null,
          _retryCache: null,
          _transitions: null,
        }),
      t.sibling
    );
  }
  function Xo(l, t, a, e, u) {
    var n = Gi();
    return (
      (n = n === null ? null : { parent: _l._currentValue, pool: n }),
      (t.memoizedState = { baseLanes: a, cachePool: n }),
      l !== null && Fu(t, null),
      Ki(),
      Zs(t),
      l !== null && me(l, t, e, !0),
      (t.childLanes = u),
      null
    );
  }
  function yn(l, t) {
    return (
      (t = rn({ mode: t.mode, children: t.children }, l.mode)),
      (t.ref = l.ref),
      (l.child = t),
      (t.return = l),
      t
    );
  }
  function Qo(l, t, a) {
    return (
      Ya(t, l.child, null, a),
      (l = yn(t, t.pendingProps)),
      (l.flags |= 2),
      ut(t),
      (t.memoizedState = null),
      l
    );
  }
  function fh(l, t, a) {
    var e = t.pendingProps,
      u = (t.flags & 128) !== 0;
    if (((t.flags &= -129), l === null)) {
      if (k) {
        if (e.mode === "hidden") return ((l = yn(t, e)), (t.lanes = 536870912), iu(null, l));
        if (
          (wi(t),
          (l = ol)
            ? ((l = P0(l, vt)),
              (l = l !== null && l.data === "&" ? l : null),
              l !== null &&
                ((t.memoizedState = {
                  dehydrated: l,
                  treeContext: ta !== null ? { id: Ot, overflow: Mt } : null,
                  retryLane: 536870912,
                  hydrationErrors: null,
                }),
                (a = Es(l)),
                (a.return = t),
                (t.child = a),
                (Ul = t),
                (ol = null)))
            : (l = null),
          l === null)
        )
          throw ea(t);
        return ((t.lanes = 536870912), null);
      }
      return yn(t, e);
    }
    var n = l.memoizedState;
    if (n !== null) {
      var i = n.dehydrated;
      if ((wi(t), u))
        if (t.flags & 256) ((t.flags &= -257), (t = Qo(l, t, a)));
        else if (t.memoizedState !== null) ((t.child = l.child), (t.flags |= 128), (t = null));
        else throw Error(d(558));
      else if ((El || me(l, t, a, !1), (u = (a & l.childLanes) !== 0), El || u)) {
        if (((e = sl), e !== null && ((i = Uf(e, a)), i !== 0 && i !== n.retryLane)))
          throw ((n.retryLane = i), Ua(l, i), $l(e, l, i), yc);
        (pn(), (t = Qo(l, t, a)));
      } else
        ((l = n.treeContext),
          (ol = gt(i.nextSibling)),
          (Ul = t),
          (k = !0),
          (aa = null),
          (vt = !1),
          l !== null && Os(t, l),
          (t = yn(t, e)),
          (t.flags |= 4096));
      return t;
    }
    return (
      (l = Ct(l.child, { mode: e.mode, children: e.children })),
      (l.ref = t.ref),
      (t.child = l),
      (l.return = t),
      l
    );
  }
  function vn(l, t) {
    var a = t.ref;
    if (a === null) l !== null && l.ref !== null && (t.flags |= 4194816);
    else {
      if (typeof a != "function" && typeof a != "object") throw Error(d(284));
      (l === null || l.ref !== a) && (t.flags |= 4194816);
    }
  }
  function vc(l, t, a, e, u) {
    return (
      xa(t),
      (a = $i(l, t, a, e, void 0, u)),
      (e = ki()),
      l !== null && !El
        ? (Fi(l, t, u), Qt(l, t, u))
        : (k && e && Ui(t), (t.flags |= 1), jl(l, t, a, u), t.child)
    );
  }
  function Zo(l, t, a, e, u, n) {
    return (
      xa(t),
      (t.updateQueue = null),
      (a = Ls(t, e, a, u)),
      Vs(l),
      (e = ki()),
      l !== null && !El
        ? (Fi(l, t, n), Qt(l, t, n))
        : (k && e && Ui(t), (t.flags |= 1), jl(l, t, a, n), t.child)
    );
  }
  function Vo(l, t, a, e, u) {
    if ((xa(t), t.stateNode === null)) {
      var n = ce,
        i = a.contextType;
      (typeof i == "object" && i !== null && (n = Hl(i)),
        (n = new a(e, n)),
        (t.memoizedState = n.state !== null && n.state !== void 0 ? n.state : null),
        (n.updater = dc),
        (t.stateNode = n),
        (n._reactInternals = t),
        (n = t.stateNode),
        (n.props = e),
        (n.state = t.memoizedState),
        (n.refs = {}),
        Qi(t),
        (i = a.contextType),
        (n.context = typeof i == "object" && i !== null ? Hl(i) : ce),
        (n.state = t.memoizedState),
        (i = a.getDerivedStateFromProps),
        typeof i == "function" && (mc(t, a, i, e), (n.state = t.memoizedState)),
        typeof a.getDerivedStateFromProps == "function" ||
          typeof n.getSnapshotBeforeUpdate == "function" ||
          (typeof n.UNSAFE_componentWillMount != "function" &&
            typeof n.componentWillMount != "function") ||
          ((i = n.state),
          typeof n.componentWillMount == "function" && n.componentWillMount(),
          typeof n.UNSAFE_componentWillMount == "function" && n.UNSAFE_componentWillMount(),
          i !== n.state && dc.enqueueReplaceState(n, n.state, null),
          tu(t, e, n, u),
          lu(),
          (n.state = t.memoizedState)),
        typeof n.componentDidMount == "function" && (t.flags |= 4194308),
        (e = !0));
    } else if (l === null) {
      n = t.stateNode;
      var c = t.memoizedProps,
        f = Xa(a, c);
      n.props = f;
      var y = n.context,
        g = a.contextType;
      ((i = ce), typeof g == "object" && g !== null && (i = Hl(g)));
      var _ = a.getDerivedStateFromProps;
      ((g = typeof _ == "function" || typeof n.getSnapshotBeforeUpdate == "function"),
        (c = t.pendingProps !== c),
        g ||
          (typeof n.UNSAFE_componentWillReceiveProps != "function" &&
            typeof n.componentWillReceiveProps != "function") ||
          ((c || y !== i) && Do(t, n, e, i)),
        (na = !1));
      var v = t.memoizedState;
      ((n.state = v),
        tu(t, e, n, u),
        lu(),
        (y = t.memoizedState),
        c || v !== y || na
          ? (typeof _ == "function" && (mc(t, a, _, e), (y = t.memoizedState)),
            (f = na || No(t, a, f, e, v, y, i))
              ? (g ||
                  (typeof n.UNSAFE_componentWillMount != "function" &&
                    typeof n.componentWillMount != "function") ||
                  (typeof n.componentWillMount == "function" && n.componentWillMount(),
                  typeof n.UNSAFE_componentWillMount == "function" &&
                    n.UNSAFE_componentWillMount()),
                typeof n.componentDidMount == "function" && (t.flags |= 4194308))
              : (typeof n.componentDidMount == "function" && (t.flags |= 4194308),
                (t.memoizedProps = e),
                (t.memoizedState = y)),
            (n.props = e),
            (n.state = y),
            (n.context = i),
            (e = f))
          : (typeof n.componentDidMount == "function" && (t.flags |= 4194308), (e = !1)));
    } else {
      ((n = t.stateNode),
        Zi(l, t),
        (i = t.memoizedProps),
        (g = Xa(a, i)),
        (n.props = g),
        (_ = t.pendingProps),
        (v = n.context),
        (y = a.contextType),
        (f = ce),
        typeof y == "object" && y !== null && (f = Hl(y)),
        (c = a.getDerivedStateFromProps),
        (y = typeof c == "function" || typeof n.getSnapshotBeforeUpdate == "function") ||
          (typeof n.UNSAFE_componentWillReceiveProps != "function" &&
            typeof n.componentWillReceiveProps != "function") ||
          ((i !== _ || v !== f) && Do(t, n, e, f)),
        (na = !1),
        (v = t.memoizedState),
        (n.state = v),
        tu(t, e, n, u),
        lu());
      var r = t.memoizedState;
      i !== _ || v !== r || na || (l !== null && l.dependencies !== null && $u(l.dependencies))
        ? (typeof c == "function" && (mc(t, a, c, e), (r = t.memoizedState)),
          (g =
            na ||
            No(t, a, g, e, v, r, f) ||
            (l !== null && l.dependencies !== null && $u(l.dependencies)))
            ? (y ||
                (typeof n.UNSAFE_componentWillUpdate != "function" &&
                  typeof n.componentWillUpdate != "function") ||
                (typeof n.componentWillUpdate == "function" && n.componentWillUpdate(e, r, f),
                typeof n.UNSAFE_componentWillUpdate == "function" &&
                  n.UNSAFE_componentWillUpdate(e, r, f)),
              typeof n.componentDidUpdate == "function" && (t.flags |= 4),
              typeof n.getSnapshotBeforeUpdate == "function" && (t.flags |= 1024))
            : (typeof n.componentDidUpdate != "function" ||
                (i === l.memoizedProps && v === l.memoizedState) ||
                (t.flags |= 4),
              typeof n.getSnapshotBeforeUpdate != "function" ||
                (i === l.memoizedProps && v === l.memoizedState) ||
                (t.flags |= 1024),
              (t.memoizedProps = e),
              (t.memoizedState = r)),
          (n.props = e),
          (n.state = r),
          (n.context = f),
          (e = g))
        : (typeof n.componentDidUpdate != "function" ||
            (i === l.memoizedProps && v === l.memoizedState) ||
            (t.flags |= 4),
          typeof n.getSnapshotBeforeUpdate != "function" ||
            (i === l.memoizedProps && v === l.memoizedState) ||
            (t.flags |= 1024),
          (e = !1));
    }
    return (
      (n = e),
      vn(l, t),
      (e = (t.flags & 128) !== 0),
      n || e
        ? ((n = t.stateNode),
          (a = e && typeof a.getDerivedStateFromError != "function" ? null : n.render()),
          (t.flags |= 1),
          l !== null && e
            ? ((t.child = Ya(t, l.child, null, u)), (t.child = Ya(t, null, a, u)))
            : jl(l, t, a, u),
          (t.memoizedState = n.state),
          (l = t.child))
        : (l = Qt(l, t, u)),
      l
    );
  }
  function Lo(l, t, a, e) {
    return (ja(), (t.flags |= 256), jl(l, t, a, e), t.child);
  }
  var rc = { dehydrated: null, treeContext: null, retryLane: 0, hydrationErrors: null };
  function gc(l) {
    return { baseLanes: l, cachePool: js() };
  }
  function Sc(l, t, a) {
    return ((l = l !== null ? l.childLanes & ~a : 0), t && (l |= it), l);
  }
  function Ko(l, t, a) {
    var e = t.pendingProps,
      u = !1,
      n = (t.flags & 128) !== 0,
      i;
    if (
      ((i = n) || (i = l !== null && l.memoizedState === null ? !1 : (bl.current & 2) !== 0),
      i && ((u = !0), (t.flags &= -129)),
      (i = (t.flags & 32) !== 0),
      (t.flags &= -33),
      l === null)
    ) {
      if (k) {
        if (
          (u ? fa(t) : sa(),
          (l = ol)
            ? ((l = P0(l, vt)),
              (l = l !== null && l.data !== "&" ? l : null),
              l !== null &&
                ((t.memoizedState = {
                  dehydrated: l,
                  treeContext: ta !== null ? { id: Ot, overflow: Mt } : null,
                  retryLane: 536870912,
                  hydrationErrors: null,
                }),
                (a = Es(l)),
                (a.return = t),
                (t.child = a),
                (Ul = t),
                (ol = null)))
            : (l = null),
          l === null)
        )
          throw ea(t);
        return (lf(l) ? (t.lanes = 32) : (t.lanes = 536870912), null);
      }
      var c = e.children;
      return (
        (e = e.fallback),
        u
          ? (sa(),
            (u = t.mode),
            (c = rn({ mode: "hidden", children: c }, u)),
            (e = Ha(e, u, a, null)),
            (c.return = t),
            (e.return = t),
            (c.sibling = e),
            (t.child = c),
            (e = t.child),
            (e.memoizedState = gc(a)),
            (e.childLanes = Sc(l, i, a)),
            (t.memoizedState = rc),
            iu(null, e))
          : (fa(t), bc(t, c))
      );
    }
    var f = l.memoizedState;
    if (f !== null && ((c = f.dehydrated), c !== null)) {
      if (n)
        t.flags & 256
          ? (fa(t), (t.flags &= -257), (t = zc(l, t, a)))
          : t.memoizedState !== null
            ? (sa(), (t.child = l.child), (t.flags |= 128), (t = null))
            : (sa(),
              (c = e.fallback),
              (u = t.mode),
              (e = rn({ mode: "visible", children: e.children }, u)),
              (c = Ha(c, u, a, null)),
              (c.flags |= 2),
              (e.return = t),
              (c.return = t),
              (e.sibling = c),
              (t.child = e),
              Ya(t, l.child, null, a),
              (e = t.child),
              (e.memoizedState = gc(a)),
              (e.childLanes = Sc(l, i, a)),
              (t.memoizedState = rc),
              (t = iu(null, e)));
      else if ((fa(t), lf(c))) {
        if (((i = c.nextSibling && c.nextSibling.dataset), i)) var y = i.dgst;
        ((i = y),
          (e = Error(d(419))),
          (e.stack = ""),
          (e.digest = i),
          We({ value: e, source: null, stack: null }),
          (t = zc(l, t, a)));
      } else if ((El || me(l, t, a, !1), (i = (a & l.childLanes) !== 0), El || i)) {
        if (((i = sl), i !== null && ((e = Uf(i, a)), e !== 0 && e !== f.retryLane)))
          throw ((f.retryLane = e), Ua(l, e), $l(i, l, e), yc);
        (Pc(c) || pn(), (t = zc(l, t, a)));
      } else
        Pc(c)
          ? ((t.flags |= 192), (t.child = l.child), (t = null))
          : ((l = f.treeContext),
            (ol = gt(c.nextSibling)),
            (Ul = t),
            (k = !0),
            (aa = null),
            (vt = !1),
            l !== null && Os(t, l),
            (t = bc(t, e.children)),
            (t.flags |= 4096));
      return t;
    }
    return u
      ? (sa(),
        (c = e.fallback),
        (u = t.mode),
        (f = l.child),
        (y = f.sibling),
        (e = Ct(f, { mode: "hidden", children: e.children })),
        (e.subtreeFlags = f.subtreeFlags & 65011712),
        y !== null ? (c = Ct(y, c)) : ((c = Ha(c, u, a, null)), (c.flags |= 2)),
        (c.return = t),
        (e.return = t),
        (e.sibling = c),
        (t.child = e),
        iu(null, e),
        (e = t.child),
        (c = l.child.memoizedState),
        c === null
          ? (c = gc(a))
          : ((u = c.cachePool),
            u !== null
              ? ((f = _l._currentValue), (u = u.parent !== f ? { parent: f, pool: f } : u))
              : (u = js()),
            (c = { baseLanes: c.baseLanes | a, cachePool: u })),
        (e.memoizedState = c),
        (e.childLanes = Sc(l, i, a)),
        (t.memoizedState = rc),
        iu(l.child, e))
      : (fa(t),
        (a = l.child),
        (l = a.sibling),
        (a = Ct(a, { mode: "visible", children: e.children })),
        (a.return = t),
        (a.sibling = null),
        l !== null &&
          ((i = t.deletions), i === null ? ((t.deletions = [l]), (t.flags |= 16)) : i.push(l)),
        (t.child = a),
        (t.memoizedState = null),
        a);
  }
  function bc(l, t) {
    return ((t = rn({ mode: "visible", children: t }, l.mode)), (t.return = l), (l.child = t));
  }
  function rn(l, t) {
    return ((l = at(22, l, null, t)), (l.lanes = 0), l);
  }
  function zc(l, t, a) {
    return (
      Ya(t, l.child, null, a),
      (l = bc(t, t.pendingProps.children)),
      (l.flags |= 2),
      (t.memoizedState = null),
      l
    );
  }
  function Jo(l, t, a) {
    l.lanes |= t;
    var e = l.alternate;
    (e !== null && (e.lanes |= t), Ci(l.return, t, a));
  }
  function _c(l, t, a, e, u, n) {
    var i = l.memoizedState;
    i === null
      ? (l.memoizedState = {
          isBackwards: t,
          rendering: null,
          renderingStartTime: 0,
          last: e,
          tail: a,
          tailMode: u,
          treeForkCount: n,
        })
      : ((i.isBackwards = t),
        (i.rendering = null),
        (i.renderingStartTime = 0),
        (i.last = e),
        (i.tail = a),
        (i.tailMode = u),
        (i.treeForkCount = n));
  }
  function wo(l, t, a) {
    var e = t.pendingProps,
      u = e.revealOrder,
      n = e.tail;
    e = e.children;
    var i = bl.current,
      c = (i & 2) !== 0;
    if (
      (c ? ((i = (i & 1) | 2), (t.flags |= 128)) : (i &= 1),
      O(bl, i),
      jl(l, t, e, a),
      (e = k ? we : 0),
      !c && l !== null && (l.flags & 128) !== 0)
    )
      l: for (l = t.child; l !== null;) {
        if (l.tag === 13) l.memoizedState !== null && Jo(l, a, t);
        else if (l.tag === 19) Jo(l, a, t);
        else if (l.child !== null) {
          ((l.child.return = l), (l = l.child));
          continue;
        }
        if (l === t) break l;
        for (; l.sibling === null;) {
          if (l.return === null || l.return === t) break l;
          l = l.return;
        }
        ((l.sibling.return = l.return), (l = l.sibling));
      }
    switch (u) {
      case "forwards":
        for (a = t.child, u = null; a !== null;)
          ((l = a.alternate), l !== null && en(l) === null && (u = a), (a = a.sibling));
        ((a = u),
          a === null ? ((u = t.child), (t.child = null)) : ((u = a.sibling), (a.sibling = null)),
          _c(t, !1, u, a, n, e));
        break;
      case "backwards":
      case "unstable_legacy-backwards":
        for (a = null, u = t.child, t.child = null; u !== null;) {
          if (((l = u.alternate), l !== null && en(l) === null)) {
            t.child = u;
            break;
          }
          ((l = u.sibling), (u.sibling = a), (a = u), (u = l));
        }
        _c(t, !0, a, null, n, e);
        break;
      case "together":
        _c(t, !1, null, null, void 0, e);
        break;
      default:
        t.memoizedState = null;
    }
    return t.child;
  }
  function Qt(l, t, a) {
    if (
      (l !== null && (t.dependencies = l.dependencies), (da |= t.lanes), (a & t.childLanes) === 0)
    )
      if (l !== null) {
        if ((me(l, t, a, !1), (a & t.childLanes) === 0)) return null;
      } else return null;
    if (l !== null && t.child !== l.child) throw Error(d(153));
    if (t.child !== null) {
      for (l = t.child, a = Ct(l, l.pendingProps), t.child = a, a.return = t; l.sibling !== null;)
        ((l = l.sibling), (a = a.sibling = Ct(l, l.pendingProps)), (a.return = t));
      a.sibling = null;
    }
    return t.child;
  }
  function Tc(l, t) {
    return (l.lanes & t) !== 0 ? !0 : ((l = l.dependencies), !!(l !== null && $u(l)));
  }
  function sh(l, t, a) {
    switch (t.tag) {
      case 3:
        (Bl(t, t.stateNode.containerInfo), ua(t, _l, l.memoizedState.cache), ja());
        break;
      case 27:
      case 5:
        je(t);
        break;
      case 4:
        Bl(t, t.stateNode.containerInfo);
        break;
      case 10:
        ua(t, t.type, t.memoizedProps.value);
        break;
      case 31:
        if (t.memoizedState !== null) return ((t.flags |= 128), wi(t), null);
        break;
      case 13:
        var e = t.memoizedState;
        if (e !== null)
          return e.dehydrated !== null
            ? (fa(t), (t.flags |= 128), null)
            : (a & t.child.childLanes) !== 0
              ? Ko(l, t, a)
              : (fa(t), (l = Qt(l, t, a)), l !== null ? l.sibling : null);
        fa(t);
        break;
      case 19:
        var u = (l.flags & 128) !== 0;
        if (
          ((e = (a & t.childLanes) !== 0),
          e || (me(l, t, a, !1), (e = (a & t.childLanes) !== 0)),
          u)
        ) {
          if (e) return wo(l, t, a);
          t.flags |= 128;
        }
        if (
          ((u = t.memoizedState),
          u !== null && ((u.rendering = null), (u.tail = null), (u.lastEffect = null)),
          O(bl, bl.current),
          e)
        )
          break;
        return null;
      case 22:
        return ((t.lanes = 0), Go(l, t, a, t.pendingProps));
      case 24:
        ua(t, _l, l.memoizedState.cache);
    }
    return Qt(l, t, a);
  }
  function Wo(l, t, a) {
    if (l !== null)
      if (l.memoizedProps !== t.pendingProps) El = !0;
      else {
        if (!Tc(l, a) && (t.flags & 128) === 0) return ((El = !1), sh(l, t, a));
        El = (l.flags & 131072) !== 0;
      }
    else ((El = !1), k && (t.flags & 1048576) !== 0 && ps(t, we, t.index));
    switch (((t.lanes = 0), t.tag)) {
      case 16:
        l: {
          var e = t.pendingProps;
          if (((l = qa(t.elementType)), (t.type = l), typeof l == "function"))
            Mi(l)
              ? ((e = Xa(l, e)), (t.tag = 1), (t = Vo(null, t, l, e, a)))
              : ((t.tag = 0), (t = vc(null, t, l, e, a)));
          else {
            if (l != null) {
              var u = l.$$typeof;
              if (u === ft) {
                ((t.tag = 11), (t = qo(null, t, l, e, a)));
                break l;
              } else if (u === $) {
                ((t.tag = 14), (t = Bo(null, t, l, e, a)));
                break l;
              }
            }
            throw ((t = Ht(l) || l), Error(d(306, t, "")));
          }
        }
        return t;
      case 0:
        return vc(l, t, t.type, t.pendingProps, a);
      case 1:
        return ((e = t.type), (u = Xa(e, t.pendingProps)), Vo(l, t, e, u, a));
      case 3:
        l: {
          if ((Bl(t, t.stateNode.containerInfo), l === null)) throw Error(d(387));
          e = t.pendingProps;
          var n = t.memoizedState;
          ((u = n.element), Zi(l, t), tu(t, e, null, a));
          var i = t.memoizedState;
          if (
            ((e = i.cache),
            ua(t, _l, e),
            e !== n.cache && qi(t, [_l], a, !0),
            lu(),
            (e = i.element),
            n.isDehydrated)
          )
            if (
              ((n = { element: e, isDehydrated: !1, cache: i.cache }),
              (t.updateQueue.baseState = n),
              (t.memoizedState = n),
              t.flags & 256)
            ) {
              t = Lo(l, t, e, a);
              break l;
            } else if (e !== u) {
              ((u = dt(Error(d(424)), t)), We(u), (t = Lo(l, t, e, a)));
              break l;
            } else
              for (
                l = t.stateNode.containerInfo,
                  l.nodeType === 9
                    ? (l = l.body)
                    : (l = l.nodeName === "HTML" ? l.ownerDocument.body : l),
                  ol = gt(l.firstChild),
                  Ul = t,
                  k = !0,
                  aa = null,
                  vt = !0,
                  a = Ys(t, null, e, a),
                  t.child = a;
                a;
              )
                ((a.flags = (a.flags & -3) | 4096), (a = a.sibling));
          else {
            if ((ja(), e === u)) {
              t = Qt(l, t, a);
              break l;
            }
            jl(l, t, e, a);
          }
          t = t.child;
        }
        return t;
      case 26:
        return (
          vn(l, t),
          l === null
            ? (a = nm(t.type, null, t.pendingProps, null))
              ? (t.memoizedState = a)
              : k ||
                ((a = t.type),
                (l = t.pendingProps),
                (e = jn(L.current).createElement(a)),
                (e[Dl] = t),
                (e[Vl] = l),
                Rl(e, a, l),
                Ol(e),
                (t.stateNode = e))
            : (t.memoizedState = nm(t.type, l.memoizedProps, t.pendingProps, l.memoizedState)),
          null
        );
      case 27:
        return (
          je(t),
          l === null &&
            k &&
            ((e = t.stateNode = am(t.type, t.pendingProps, L.current)),
            (Ul = t),
            (vt = !0),
            (u = ol),
            ga(t.type) ? ((tf = u), (ol = gt(e.firstChild))) : (ol = u)),
          jl(l, t, t.pendingProps.children, a),
          vn(l, t),
          l === null && (t.flags |= 4194304),
          t.child
        );
      case 5:
        return (
          l === null &&
            k &&
            ((u = e = ol) &&
              ((e = Gh(e, t.type, t.pendingProps, vt)),
              e !== null
                ? ((t.stateNode = e), (Ul = t), (ol = gt(e.firstChild)), (vt = !1), (u = !0))
                : (u = !1)),
            u || ea(t)),
          je(t),
          (u = t.type),
          (n = t.pendingProps),
          (i = l !== null ? l.memoizedProps : null),
          (e = n.children),
          kc(u, n) ? (e = null) : i !== null && kc(u, i) && (t.flags |= 32),
          t.memoizedState !== null && ((u = $i(l, t, lh, null, null, a)), (_u._currentValue = u)),
          vn(l, t),
          jl(l, t, e, a),
          t.child
        );
      case 6:
        return (
          l === null &&
            k &&
            ((l = a = ol) &&
              ((a = Xh(a, t.pendingProps, vt)),
              a !== null ? ((t.stateNode = a), (Ul = t), (ol = null), (l = !0)) : (l = !1)),
            l || ea(t)),
          null
        );
      case 13:
        return Ko(l, t, a);
      case 4:
        return (
          Bl(t, t.stateNode.containerInfo),
          (e = t.pendingProps),
          l === null ? (t.child = Ya(t, null, e, a)) : jl(l, t, e, a),
          t.child
        );
      case 11:
        return qo(l, t, t.type, t.pendingProps, a);
      case 7:
        return (jl(l, t, t.pendingProps, a), t.child);
      case 8:
        return (jl(l, t, t.pendingProps.children, a), t.child);
      case 12:
        return (jl(l, t, t.pendingProps.children, a), t.child);
      case 10:
        return ((e = t.pendingProps), ua(t, t.type, e.value), jl(l, t, e.children, a), t.child);
      case 9:
        return (
          (u = t.type._context),
          (e = t.pendingProps.children),
          xa(t),
          (u = Hl(u)),
          (e = e(u)),
          (t.flags |= 1),
          jl(l, t, e, a),
          t.child
        );
      case 14:
        return Bo(l, t, t.type, t.pendingProps, a);
      case 15:
        return Yo(l, t, t.type, t.pendingProps, a);
      case 19:
        return wo(l, t, a);
      case 31:
        return fh(l, t, a);
      case 22:
        return Go(l, t, a, t.pendingProps);
      case 24:
        return (
          xa(t),
          (e = Hl(_l)),
          l === null
            ? ((u = Gi()),
              u === null &&
                ((u = sl),
                (n = Bi()),
                (u.pooledCache = n),
                n.refCount++,
                n !== null && (u.pooledCacheLanes |= a),
                (u = n)),
              (t.memoizedState = { parent: e, cache: u }),
              Qi(t),
              ua(t, _l, u))
            : ((l.lanes & a) !== 0 && (Zi(l, t), tu(t, null, null, a), lu()),
              (u = l.memoizedState),
              (n = t.memoizedState),
              u.parent !== e
                ? ((u = { parent: e, cache: e }),
                  (t.memoizedState = u),
                  t.lanes === 0 && (t.memoizedState = t.updateQueue.baseState = u),
                  ua(t, _l, e))
                : ((e = n.cache), ua(t, _l, e), e !== u.cache && qi(t, [_l], a, !0))),
          jl(l, t, t.pendingProps.children, a),
          t.child
        );
      case 29:
        throw t.pendingProps;
    }
    throw Error(d(156, t.tag));
  }
  function Zt(l) {
    l.flags |= 4;
  }
  function Ec(l, t, a, e, u) {
    if (((t = (l.mode & 32) !== 0) && (t = !1), t)) {
      if (((l.flags |= 16777216), (u & 335544128) === u))
        if (l.stateNode.complete) l.flags |= 8192;
        else if (_0()) l.flags |= 8192;
        else throw ((Ba = Pu), Xi);
    } else l.flags &= -16777217;
  }
  function $o(l, t) {
    if (t.type !== "stylesheet" || (t.state.loading & 4) !== 0) l.flags &= -16777217;
    else if (((l.flags |= 16777216), !om(t)))
      if (_0()) l.flags |= 8192;
      else throw ((Ba = Pu), Xi);
  }
  function gn(l, t) {
    (t !== null && (l.flags |= 4),
      l.flags & 16384 && ((t = l.tag !== 22 ? Mf() : 536870912), (l.lanes |= t), (Ee |= t)));
  }
  function cu(l, t) {
    if (!k)
      switch (l.tailMode) {
        case "hidden":
          t = l.tail;
          for (var a = null; t !== null;) (t.alternate !== null && (a = t), (t = t.sibling));
          a === null ? (l.tail = null) : (a.sibling = null);
          break;
        case "collapsed":
          a = l.tail;
          for (var e = null; a !== null;) (a.alternate !== null && (e = a), (a = a.sibling));
          e === null
            ? t || l.tail === null
              ? (l.tail = null)
              : (l.tail.sibling = null)
            : (e.sibling = null);
      }
  }
  function ml(l) {
    var t = l.alternate !== null && l.alternate.child === l.child,
      a = 0,
      e = 0;
    if (t)
      for (var u = l.child; u !== null;)
        ((a |= u.lanes | u.childLanes),
          (e |= u.subtreeFlags & 65011712),
          (e |= u.flags & 65011712),
          (u.return = l),
          (u = u.sibling));
    else
      for (u = l.child; u !== null;)
        ((a |= u.lanes | u.childLanes),
          (e |= u.subtreeFlags),
          (e |= u.flags),
          (u.return = l),
          (u = u.sibling));
    return ((l.subtreeFlags |= e), (l.childLanes = a), t);
  }
  function oh(l, t, a) {
    var e = t.pendingProps;
    switch ((Hi(t), t.tag)) {
      case 16:
      case 15:
      case 0:
      case 11:
      case 7:
      case 8:
      case 12:
      case 9:
      case 14:
        return (ml(t), null);
      case 1:
        return (ml(t), null);
      case 3:
        return (
          (a = t.stateNode),
          (e = null),
          l !== null && (e = l.memoizedState.cache),
          t.memoizedState.cache !== e && (t.flags |= 2048),
          Yt(_l),
          Sl(),
          a.pendingContext && ((a.context = a.pendingContext), (a.pendingContext = null)),
          (l === null || l.child === null) &&
            (oe(t)
              ? Zt(t)
              : l === null ||
                (l.memoizedState.isDehydrated && (t.flags & 256) === 0) ||
                ((t.flags |= 1024), Ri())),
          ml(t),
          null
        );
      case 26:
        var u = t.type,
          n = t.memoizedState;
        return (
          l === null
            ? (Zt(t), n !== null ? (ml(t), $o(t, n)) : (ml(t), Ec(t, u, null, e, a)))
            : n
              ? n !== l.memoizedState
                ? (Zt(t), ml(t), $o(t, n))
                : (ml(t), (t.flags &= -16777217))
              : ((l = l.memoizedProps), l !== e && Zt(t), ml(t), Ec(t, u, l, e, a)),
          null
        );
      case 27:
        if ((Mu(t), (a = L.current), (u = t.type), l !== null && t.stateNode != null))
          l.memoizedProps !== e && Zt(t);
        else {
          if (!e) {
            if (t.stateNode === null) throw Error(d(166));
            return (ml(t), null);
          }
          ((l = U.current), oe(t) ? Ms(t) : ((l = am(u, e, a)), (t.stateNode = l), Zt(t)));
        }
        return (ml(t), null);
      case 5:
        if ((Mu(t), (u = t.type), l !== null && t.stateNode != null))
          l.memoizedProps !== e && Zt(t);
        else {
          if (!e) {
            if (t.stateNode === null) throw Error(d(166));
            return (ml(t), null);
          }
          if (((n = U.current), oe(t))) Ms(t);
          else {
            var i = jn(L.current);
            switch (n) {
              case 1:
                n = i.createElementNS("http://www.w3.org/2000/svg", u);
                break;
              case 2:
                n = i.createElementNS("http://www.w3.org/1998/Math/MathML", u);
                break;
              default:
                switch (u) {
                  case "svg":
                    n = i.createElementNS("http://www.w3.org/2000/svg", u);
                    break;
                  case "math":
                    n = i.createElementNS("http://www.w3.org/1998/Math/MathML", u);
                    break;
                  case "script":
                    ((n = i.createElement("div")),
                      (n.innerHTML = "<script><\/script>"),
                      (n = n.removeChild(n.firstChild)));
                    break;
                  case "select":
                    ((n =
                      typeof e.is == "string"
                        ? i.createElement("select", { is: e.is })
                        : i.createElement("select")),
                      e.multiple ? (n.multiple = !0) : e.size && (n.size = e.size));
                    break;
                  default:
                    n =
                      typeof e.is == "string"
                        ? i.createElement(u, { is: e.is })
                        : i.createElement(u);
                }
            }
            ((n[Dl] = t), (n[Vl] = e));
            l: for (i = t.child; i !== null;) {
              if (i.tag === 5 || i.tag === 6) n.appendChild(i.stateNode);
              else if (i.tag !== 4 && i.tag !== 27 && i.child !== null) {
                ((i.child.return = i), (i = i.child));
                continue;
              }
              if (i === t) break l;
              for (; i.sibling === null;) {
                if (i.return === null || i.return === t) break l;
                i = i.return;
              }
              ((i.sibling.return = i.return), (i = i.sibling));
            }
            t.stateNode = n;
            l: switch ((Rl(n, u, e), u)) {
              case "button":
              case "input":
              case "select":
              case "textarea":
                e = !!e.autoFocus;
                break l;
              case "img":
                e = !0;
                break l;
              default:
                e = !1;
            }
            e && Zt(t);
          }
        }
        return (ml(t), Ec(t, t.type, l === null ? null : l.memoizedProps, t.pendingProps, a), null);
      case 6:
        if (l && t.stateNode != null) l.memoizedProps !== e && Zt(t);
        else {
          if (typeof e != "string" && t.stateNode === null) throw Error(d(166));
          if (((l = L.current), oe(t))) {
            if (((l = t.stateNode), (a = t.memoizedProps), (e = null), (u = Ul), u !== null))
              switch (u.tag) {
                case 27:
                case 5:
                  e = u.memoizedProps;
              }
            ((l[Dl] = t),
              (l = !!(
                l.nodeValue === a ||
                (e !== null && e.suppressHydrationWarning === !0) ||
                K0(l.nodeValue, a)
              )),
              l || ea(t, !0));
          } else ((l = jn(l).createTextNode(e)), (l[Dl] = t), (t.stateNode = l));
        }
        return (ml(t), null);
      case 31:
        if (((a = t.memoizedState), l === null || l.memoizedState !== null)) {
          if (((e = oe(t)), a !== null)) {
            if (l === null) {
              if (!e) throw Error(d(318));
              if (((l = t.memoizedState), (l = l !== null ? l.dehydrated : null), !l))
                throw Error(d(557));
              l[Dl] = t;
            } else (ja(), (t.flags & 128) === 0 && (t.memoizedState = null), (t.flags |= 4));
            (ml(t), (l = !1));
          } else
            ((a = Ri()),
              l !== null && l.memoizedState !== null && (l.memoizedState.hydrationErrors = a),
              (l = !0));
          if (!l) return t.flags & 256 ? (ut(t), t) : (ut(t), null);
          if ((t.flags & 128) !== 0) throw Error(d(558));
        }
        return (ml(t), null);
      case 13:
        if (
          ((e = t.memoizedState),
          l === null || (l.memoizedState !== null && l.memoizedState.dehydrated !== null))
        ) {
          if (((u = oe(t)), e !== null && e.dehydrated !== null)) {
            if (l === null) {
              if (!u) throw Error(d(318));
              if (((u = t.memoizedState), (u = u !== null ? u.dehydrated : null), !u))
                throw Error(d(317));
              u[Dl] = t;
            } else (ja(), (t.flags & 128) === 0 && (t.memoizedState = null), (t.flags |= 4));
            (ml(t), (u = !1));
          } else
            ((u = Ri()),
              l !== null && l.memoizedState !== null && (l.memoizedState.hydrationErrors = u),
              (u = !0));
          if (!u) return t.flags & 256 ? (ut(t), t) : (ut(t), null);
        }
        return (
          ut(t),
          (t.flags & 128) !== 0
            ? ((t.lanes = a), t)
            : ((a = e !== null),
              (l = l !== null && l.memoizedState !== null),
              a &&
                ((e = t.child),
                (u = null),
                e.alternate !== null &&
                  e.alternate.memoizedState !== null &&
                  e.alternate.memoizedState.cachePool !== null &&
                  (u = e.alternate.memoizedState.cachePool.pool),
                (n = null),
                e.memoizedState !== null &&
                  e.memoizedState.cachePool !== null &&
                  (n = e.memoizedState.cachePool.pool),
                n !== u && (e.flags |= 2048)),
              a !== l && a && (t.child.flags |= 8192),
              gn(t, t.updateQueue),
              ml(t),
              null)
        );
      case 4:
        return (Sl(), l === null && Kc(t.stateNode.containerInfo), ml(t), null);
      case 10:
        return (Yt(t.type), ml(t), null);
      case 19:
        if ((T(bl), (e = t.memoizedState), e === null)) return (ml(t), null);
        if (((u = (t.flags & 128) !== 0), (n = e.rendering), n === null))
          if (u) cu(e, !1);
          else {
            if (gl !== 0 || (l !== null && (l.flags & 128) !== 0))
              for (l = t.child; l !== null;) {
                if (((n = en(l)), n !== null)) {
                  for (
                    t.flags |= 128,
                      cu(e, !1),
                      l = n.updateQueue,
                      t.updateQueue = l,
                      gn(t, l),
                      t.subtreeFlags = 0,
                      l = a,
                      a = t.child;
                    a !== null;
                  )
                    (Ts(a, l), (a = a.sibling));
                  return (O(bl, (bl.current & 1) | 2), k && qt(t, e.treeForkCount), t.child);
                }
                l = l.sibling;
              }
            e.tail !== null &&
              Il() > Tn &&
              ((t.flags |= 128), (u = !0), cu(e, !1), (t.lanes = 4194304));
          }
        else {
          if (!u)
            if (((l = en(n)), l !== null)) {
              if (
                ((t.flags |= 128),
                (u = !0),
                (l = l.updateQueue),
                (t.updateQueue = l),
                gn(t, l),
                cu(e, !0),
                e.tail === null && e.tailMode === "hidden" && !n.alternate && !k)
              )
                return (ml(t), null);
            } else
              2 * Il() - e.renderingStartTime > Tn &&
                a !== 536870912 &&
                ((t.flags |= 128), (u = !0), cu(e, !1), (t.lanes = 4194304));
          e.isBackwards
            ? ((n.sibling = t.child), (t.child = n))
            : ((l = e.last), l !== null ? (l.sibling = n) : (t.child = n), (e.last = n));
        }
        return e.tail !== null
          ? ((l = e.tail),
            (e.rendering = l),
            (e.tail = l.sibling),
            (e.renderingStartTime = Il()),
            (l.sibling = null),
            (a = bl.current),
            O(bl, u ? (a & 1) | 2 : a & 1),
            k && qt(t, e.treeForkCount),
            l)
          : (ml(t), null);
      case 22:
      case 23:
        return (
          ut(t),
          Ji(),
          (e = t.memoizedState !== null),
          l !== null
            ? (l.memoizedState !== null) !== e && (t.flags |= 8192)
            : e && (t.flags |= 8192),
          e
            ? (a & 536870912) !== 0 &&
              (t.flags & 128) === 0 &&
              (ml(t), t.subtreeFlags & 6 && (t.flags |= 8192))
            : ml(t),
          (a = t.updateQueue),
          a !== null && gn(t, a.retryQueue),
          (a = null),
          l !== null &&
            l.memoizedState !== null &&
            l.memoizedState.cachePool !== null &&
            (a = l.memoizedState.cachePool.pool),
          (e = null),
          t.memoizedState !== null &&
            t.memoizedState.cachePool !== null &&
            (e = t.memoizedState.cachePool.pool),
          e !== a && (t.flags |= 2048),
          l !== null && T(Ca),
          null
        );
      case 24:
        return (
          (a = null),
          l !== null && (a = l.memoizedState.cache),
          t.memoizedState.cache !== a && (t.flags |= 2048),
          Yt(_l),
          ml(t),
          null
        );
      case 25:
        return null;
      case 30:
        return null;
    }
    throw Error(d(156, t.tag));
  }
  function mh(l, t) {
    switch ((Hi(t), t.tag)) {
      case 1:
        return ((l = t.flags), l & 65536 ? ((t.flags = (l & -65537) | 128), t) : null);
      case 3:
        return (
          Yt(_l),
          Sl(),
          (l = t.flags),
          (l & 65536) !== 0 && (l & 128) === 0 ? ((t.flags = (l & -65537) | 128), t) : null
        );
      case 26:
      case 27:
      case 5:
        return (Mu(t), null);
      case 31:
        if (t.memoizedState !== null) {
          if ((ut(t), t.alternate === null)) throw Error(d(340));
          ja();
        }
        return ((l = t.flags), l & 65536 ? ((t.flags = (l & -65537) | 128), t) : null);
      case 13:
        if ((ut(t), (l = t.memoizedState), l !== null && l.dehydrated !== null)) {
          if (t.alternate === null) throw Error(d(340));
          ja();
        }
        return ((l = t.flags), l & 65536 ? ((t.flags = (l & -65537) | 128), t) : null);
      case 19:
        return (T(bl), null);
      case 4:
        return (Sl(), null);
      case 10:
        return (Yt(t.type), null);
      case 22:
      case 23:
        return (
          ut(t),
          Ji(),
          l !== null && T(Ca),
          (l = t.flags),
          l & 65536 ? ((t.flags = (l & -65537) | 128), t) : null
        );
      case 24:
        return (Yt(_l), null);
      case 25:
        return null;
      default:
        return null;
    }
  }
  function ko(l, t) {
    switch ((Hi(t), t.tag)) {
      case 3:
        (Yt(_l), Sl());
        break;
      case 26:
      case 27:
      case 5:
        Mu(t);
        break;
      case 4:
        Sl();
        break;
      case 31:
        t.memoizedState !== null && ut(t);
        break;
      case 13:
        ut(t);
        break;
      case 19:
        T(bl);
        break;
      case 10:
        Yt(t.type);
        break;
      case 22:
      case 23:
        (ut(t), Ji(), l !== null && T(Ca));
        break;
      case 24:
        Yt(_l);
    }
  }
  function fu(l, t) {
    try {
      var a = t.updateQueue,
        e = a !== null ? a.lastEffect : null;
      if (e !== null) {
        var u = e.next;
        a = u;
        do {
          if ((a.tag & l) === l) {
            e = void 0;
            var n = a.create,
              i = a.inst;
            ((e = n()), (i.destroy = e));
          }
          a = a.next;
        } while (a !== u);
      }
    } catch (c) {
      el(t, t.return, c);
    }
  }
  function oa(l, t, a) {
    try {
      var e = t.updateQueue,
        u = e !== null ? e.lastEffect : null;
      if (u !== null) {
        var n = u.next;
        e = n;
        do {
          if ((e.tag & l) === l) {
            var i = e.inst,
              c = i.destroy;
            if (c !== void 0) {
              ((i.destroy = void 0), (u = t));
              var f = a,
                y = c;
              try {
                y();
              } catch (g) {
                el(u, f, g);
              }
            }
          }
          e = e.next;
        } while (e !== n);
      }
    } catch (g) {
      el(t, t.return, g);
    }
  }
  function Fo(l) {
    var t = l.updateQueue;
    if (t !== null) {
      var a = l.stateNode;
      try {
        Xs(t, a);
      } catch (e) {
        el(l, l.return, e);
      }
    }
  }
  function Io(l, t, a) {
    ((a.props = Xa(l.type, l.memoizedProps)), (a.state = l.memoizedState));
    try {
      a.componentWillUnmount();
    } catch (e) {
      el(l, t, e);
    }
  }
  function su(l, t) {
    try {
      var a = l.ref;
      if (a !== null) {
        switch (l.tag) {
          case 26:
          case 27:
          case 5:
            var e = l.stateNode;
            break;
          case 30:
            e = l.stateNode;
            break;
          default:
            e = l.stateNode;
        }
        typeof a == "function" ? (l.refCleanup = a(e)) : (a.current = e);
      }
    } catch (u) {
      el(l, t, u);
    }
  }
  function Nt(l, t) {
    var a = l.ref,
      e = l.refCleanup;
    if (a !== null)
      if (typeof e == "function")
        try {
          e();
        } catch (u) {
          el(l, t, u);
        } finally {
          ((l.refCleanup = null), (l = l.alternate), l != null && (l.refCleanup = null));
        }
      else if (typeof a == "function")
        try {
          a(null);
        } catch (u) {
          el(l, t, u);
        }
      else a.current = null;
  }
  function Po(l) {
    var t = l.type,
      a = l.memoizedProps,
      e = l.stateNode;
    try {
      l: switch (t) {
        case "button":
        case "input":
        case "select":
        case "textarea":
          a.autoFocus && e.focus();
          break l;
        case "img":
          a.src ? (e.src = a.src) : a.srcSet && (e.srcset = a.srcSet);
      }
    } catch (u) {
      el(l, l.return, u);
    }
  }
  function Ac(l, t, a) {
    try {
      var e = l.stateNode;
      (Rh(e, l.type, a, t), (e[Vl] = t));
    } catch (u) {
      el(l, l.return, u);
    }
  }
  function l0(l) {
    return (
      l.tag === 5 || l.tag === 3 || l.tag === 26 || (l.tag === 27 && ga(l.type)) || l.tag === 4
    );
  }
  function pc(l) {
    l: for (;;) {
      for (; l.sibling === null;) {
        if (l.return === null || l0(l.return)) return null;
        l = l.return;
      }
      for (
        l.sibling.return = l.return, l = l.sibling;
        l.tag !== 5 && l.tag !== 6 && l.tag !== 18;
      ) {
        if ((l.tag === 27 && ga(l.type)) || l.flags & 2 || l.child === null || l.tag === 4)
          continue l;
        ((l.child.return = l), (l = l.child));
      }
      if (!(l.flags & 2)) return l.stateNode;
    }
  }
  function Oc(l, t, a) {
    var e = l.tag;
    if (e === 5 || e === 6)
      ((l = l.stateNode),
        t
          ? (a.nodeType === 9
              ? a.body
              : a.nodeName === "HTML"
                ? a.ownerDocument.body
                : a
            ).insertBefore(l, t)
          : ((t = a.nodeType === 9 ? a.body : a.nodeName === "HTML" ? a.ownerDocument.body : a),
            t.appendChild(l),
            (a = a._reactRootContainer),
            a != null || t.onclick !== null || (t.onclick = Rt)));
    else if (
      e !== 4 &&
      (e === 27 && ga(l.type) && ((a = l.stateNode), (t = null)), (l = l.child), l !== null)
    )
      for (Oc(l, t, a), l = l.sibling; l !== null;) (Oc(l, t, a), (l = l.sibling));
  }
  function Sn(l, t, a) {
    var e = l.tag;
    if (e === 5 || e === 6) ((l = l.stateNode), t ? a.insertBefore(l, t) : a.appendChild(l));
    else if (e !== 4 && (e === 27 && ga(l.type) && (a = l.stateNode), (l = l.child), l !== null))
      for (Sn(l, t, a), l = l.sibling; l !== null;) (Sn(l, t, a), (l = l.sibling));
  }
  function t0(l) {
    var t = l.stateNode,
      a = l.memoizedProps;
    try {
      for (var e = l.type, u = t.attributes; u.length;) t.removeAttributeNode(u[0]);
      (Rl(t, e, a), (t[Dl] = l), (t[Vl] = a));
    } catch (n) {
      el(l, l.return, n);
    }
  }
  var Vt = !1,
    Al = !1,
    Mc = !1,
    a0 = typeof WeakSet == "function" ? WeakSet : Set,
    Ml = null;
  function dh(l, t) {
    if (((l = l.containerInfo), (Wc = Gn), (l = hs(l)), zi(l))) {
      if ("selectionStart" in l) var a = { start: l.selectionStart, end: l.selectionEnd };
      else
        l: {
          a = ((a = l.ownerDocument) && a.defaultView) || window;
          var e = a.getSelection && a.getSelection();
          if (e && e.rangeCount !== 0) {
            a = e.anchorNode;
            var u = e.anchorOffset,
              n = e.focusNode;
            e = e.focusOffset;
            try {
              (a.nodeType, n.nodeType);
            } catch {
              a = null;
              break l;
            }
            var i = 0,
              c = -1,
              f = -1,
              y = 0,
              g = 0,
              _ = l,
              v = null;
            t: for (;;) {
              for (
                var r;
                _ !== a || (u !== 0 && _.nodeType !== 3) || (c = i + u),
                  _ !== n || (e !== 0 && _.nodeType !== 3) || (f = i + e),
                  _.nodeType === 3 && (i += _.nodeValue.length),
                  (r = _.firstChild) !== null;
              )
                ((v = _), (_ = r));
              for (;;) {
                if (_ === l) break t;
                if (
                  (v === a && ++y === u && (c = i),
                  v === n && ++g === e && (f = i),
                  (r = _.nextSibling) !== null)
                )
                  break;
                ((_ = v), (v = _.parentNode));
              }
              _ = r;
            }
            a = c === -1 || f === -1 ? null : { start: c, end: f };
          } else a = null;
        }
      a = a || { start: 0, end: 0 };
    } else a = null;
    for ($c = { focusedElem: l, selectionRange: a }, Gn = !1, Ml = t; Ml !== null;)
      if (((t = Ml), (l = t.child), (t.subtreeFlags & 1028) !== 0 && l !== null))
        ((l.return = t), (Ml = l));
      else
        for (; Ml !== null;) {
          switch (((t = Ml), (n = t.alternate), (l = t.flags), t.tag)) {
            case 0:
              if (
                (l & 4) !== 0 &&
                ((l = t.updateQueue), (l = l !== null ? l.events : null), l !== null)
              )
                for (a = 0; a < l.length; a++) ((u = l[a]), (u.ref.impl = u.nextImpl));
              break;
            case 11:
            case 15:
              break;
            case 1:
              if ((l & 1024) !== 0 && n !== null) {
                ((l = void 0),
                  (a = t),
                  (u = n.memoizedProps),
                  (n = n.memoizedState),
                  (e = a.stateNode));
                try {
                  var M = Xa(a.type, u);
                  ((l = e.getSnapshotBeforeUpdate(M, n)),
                    (e.__reactInternalSnapshotBeforeUpdate = l));
                } catch (C) {
                  el(a, a.return, C);
                }
              }
              break;
            case 3:
              if ((l & 1024) !== 0) {
                if (((l = t.stateNode.containerInfo), (a = l.nodeType), a === 9)) Ic(l);
                else if (a === 1)
                  switch (l.nodeName) {
                    case "HEAD":
                    case "HTML":
                    case "BODY":
                      Ic(l);
                      break;
                    default:
                      l.textContent = "";
                  }
              }
              break;
            case 5:
            case 26:
            case 27:
            case 6:
            case 4:
            case 17:
              break;
            default:
              if ((l & 1024) !== 0) throw Error(d(163));
          }
          if (((l = t.sibling), l !== null)) {
            ((l.return = t.return), (Ml = l));
            break;
          }
          Ml = t.return;
        }
  }
  function e0(l, t, a) {
    var e = a.flags;
    switch (a.tag) {
      case 0:
      case 11:
      case 15:
        (Kt(l, a), e & 4 && fu(5, a));
        break;
      case 1:
        if ((Kt(l, a), e & 4))
          if (((l = a.stateNode), t === null))
            try {
              l.componentDidMount();
            } catch (i) {
              el(a, a.return, i);
            }
          else {
            var u = Xa(a.type, t.memoizedProps);
            t = t.memoizedState;
            try {
              l.componentDidUpdate(u, t, l.__reactInternalSnapshotBeforeUpdate);
            } catch (i) {
              el(a, a.return, i);
            }
          }
        (e & 64 && Fo(a), e & 512 && su(a, a.return));
        break;
      case 3:
        if ((Kt(l, a), e & 64 && ((l = a.updateQueue), l !== null))) {
          if (((t = null), a.child !== null))
            switch (a.child.tag) {
              case 27:
              case 5:
                t = a.child.stateNode;
                break;
              case 1:
                t = a.child.stateNode;
            }
          try {
            Xs(l, t);
          } catch (i) {
            el(a, a.return, i);
          }
        }
        break;
      case 27:
        t === null && e & 4 && t0(a);
      case 26:
      case 5:
        (Kt(l, a), t === null && e & 4 && Po(a), e & 512 && su(a, a.return));
        break;
      case 12:
        Kt(l, a);
        break;
      case 31:
        (Kt(l, a), e & 4 && i0(l, a));
        break;
      case 13:
        (Kt(l, a),
          e & 4 && c0(l, a),
          e & 64 &&
            ((l = a.memoizedState),
            l !== null && ((l = l.dehydrated), l !== null && ((a = _h.bind(null, a)), Qh(l, a)))));
        break;
      case 22:
        if (((e = a.memoizedState !== null || Vt), !e)) {
          ((t = (t !== null && t.memoizedState !== null) || Al), (u = Vt));
          var n = Al;
          ((Vt = e),
            (Al = t) && !n ? Jt(l, a, (a.subtreeFlags & 8772) !== 0) : Kt(l, a),
            (Vt = u),
            (Al = n));
        }
        break;
      case 30:
        break;
      default:
        Kt(l, a);
    }
  }
  function u0(l) {
    var t = l.alternate;
    (t !== null && ((l.alternate = null), u0(t)),
      (l.child = null),
      (l.deletions = null),
      (l.sibling = null),
      l.tag === 5 && ((t = l.stateNode), t !== null && ei(t)),
      (l.stateNode = null),
      (l.return = null),
      (l.dependencies = null),
      (l.memoizedProps = null),
      (l.memoizedState = null),
      (l.pendingProps = null),
      (l.stateNode = null),
      (l.updateQueue = null));
  }
  var hl = null,
    Kl = !1;
  function Lt(l, t, a) {
    for (a = a.child; a !== null;) (n0(l, t, a), (a = a.sibling));
  }
  function n0(l, t, a) {
    if (Pl && typeof Pl.onCommitFiberUnmount == "function")
      try {
        Pl.onCommitFiberUnmount(Re, a);
      } catch {}
    switch (a.tag) {
      case 26:
        (Al || Nt(a, t),
          Lt(l, t, a),
          a.memoizedState
            ? a.memoizedState.count--
            : a.stateNode && ((a = a.stateNode), a.parentNode.removeChild(a)));
        break;
      case 27:
        Al || Nt(a, t);
        var e = hl,
          u = Kl;
        (ga(a.type) && ((hl = a.stateNode), (Kl = !1)),
          Lt(l, t, a),
          Su(a.stateNode),
          (hl = e),
          (Kl = u));
        break;
      case 5:
        Al || Nt(a, t);
      case 6:
        if (((e = hl), (u = Kl), (hl = null), Lt(l, t, a), (hl = e), (Kl = u), hl !== null))
          if (Kl)
            try {
              (hl.nodeType === 9
                ? hl.body
                : hl.nodeName === "HTML"
                  ? hl.ownerDocument.body
                  : hl
              ).removeChild(a.stateNode);
            } catch (n) {
              el(a, t, n);
            }
          else
            try {
              hl.removeChild(a.stateNode);
            } catch (n) {
              el(a, t, n);
            }
        break;
      case 18:
        hl !== null &&
          (Kl
            ? ((l = hl),
              F0(
                l.nodeType === 9 ? l.body : l.nodeName === "HTML" ? l.ownerDocument.body : l,
                a.stateNode,
              ),
              He(l))
            : F0(hl, a.stateNode));
        break;
      case 4:
        ((e = hl),
          (u = Kl),
          (hl = a.stateNode.containerInfo),
          (Kl = !0),
          Lt(l, t, a),
          (hl = e),
          (Kl = u));
        break;
      case 0:
      case 11:
      case 14:
      case 15:
        (oa(2, a, t), Al || oa(4, a, t), Lt(l, t, a));
        break;
      case 1:
        (Al ||
          (Nt(a, t), (e = a.stateNode), typeof e.componentWillUnmount == "function" && Io(a, t, e)),
          Lt(l, t, a));
        break;
      case 21:
        Lt(l, t, a);
        break;
      case 22:
        ((Al = (e = Al) || a.memoizedState !== null), Lt(l, t, a), (Al = e));
        break;
      default:
        Lt(l, t, a);
    }
  }
  function i0(l, t) {
    if (
      t.memoizedState === null &&
      ((l = t.alternate), l !== null && ((l = l.memoizedState), l !== null))
    ) {
      l = l.dehydrated;
      try {
        He(l);
      } catch (a) {
        el(t, t.return, a);
      }
    }
  }
  function c0(l, t) {
    if (
      t.memoizedState === null &&
      ((l = t.alternate),
      l !== null && ((l = l.memoizedState), l !== null && ((l = l.dehydrated), l !== null)))
    )
      try {
        He(l);
      } catch (a) {
        el(t, t.return, a);
      }
  }
  function hh(l) {
    switch (l.tag) {
      case 31:
      case 13:
      case 19:
        var t = l.stateNode;
        return (t === null && (t = l.stateNode = new a0()), t);
      case 22:
        return (
          (l = l.stateNode),
          (t = l._retryCache),
          t === null && (t = l._retryCache = new a0()),
          t
        );
      default:
        throw Error(d(435, l.tag));
    }
  }
  function bn(l, t) {
    var a = hh(l);
    t.forEach(function (e) {
      if (!a.has(e)) {
        a.add(e);
        var u = Th.bind(null, l, e);
        e.then(u, u);
      }
    });
  }
  function Jl(l, t) {
    var a = t.deletions;
    if (a !== null)
      for (var e = 0; e < a.length; e++) {
        var u = a[e],
          n = l,
          i = t,
          c = i;
        l: for (; c !== null;) {
          switch (c.tag) {
            case 27:
              if (ga(c.type)) {
                ((hl = c.stateNode), (Kl = !1));
                break l;
              }
              break;
            case 5:
              ((hl = c.stateNode), (Kl = !1));
              break l;
            case 3:
            case 4:
              ((hl = c.stateNode.containerInfo), (Kl = !0));
              break l;
          }
          c = c.return;
        }
        if (hl === null) throw Error(d(160));
        (n0(n, i, u),
          (hl = null),
          (Kl = !1),
          (n = u.alternate),
          n !== null && (n.return = null),
          (u.return = null));
      }
    if (t.subtreeFlags & 13886) for (t = t.child; t !== null;) (f0(t, l), (t = t.sibling));
  }
  var _t = null;
  function f0(l, t) {
    var a = l.alternate,
      e = l.flags;
    switch (l.tag) {
      case 0:
      case 11:
      case 14:
      case 15:
        (Jl(t, l), wl(l), e & 4 && (oa(3, l, l.return), fu(3, l), oa(5, l, l.return)));
        break;
      case 1:
        (Jl(t, l),
          wl(l),
          e & 512 && (Al || a === null || Nt(a, a.return)),
          e & 64 &&
            Vt &&
            ((l = l.updateQueue),
            l !== null &&
              ((e = l.callbacks),
              e !== null &&
                ((a = l.shared.hiddenCallbacks),
                (l.shared.hiddenCallbacks = a === null ? e : a.concat(e))))));
        break;
      case 26:
        var u = _t;
        if ((Jl(t, l), wl(l), e & 512 && (Al || a === null || Nt(a, a.return)), e & 4)) {
          var n = a !== null ? a.memoizedState : null;
          if (((e = l.memoizedState), a === null))
            if (e === null)
              if (l.stateNode === null) {
                l: {
                  ((e = l.type), (a = l.memoizedProps), (u = u.ownerDocument || u));
                  t: switch (e) {
                    case "title":
                      ((n = u.getElementsByTagName("title")[0]),
                        (!n ||
                          n[qe] ||
                          n[Dl] ||
                          n.namespaceURI === "http://www.w3.org/2000/svg" ||
                          n.hasAttribute("itemprop")) &&
                          ((n = u.createElement(e)),
                          u.head.insertBefore(n, u.querySelector("head > title"))),
                        Rl(n, e, a),
                        (n[Dl] = l),
                        Ol(n),
                        (e = n));
                      break l;
                    case "link":
                      var i = fm("link", "href", u).get(e + (a.href || ""));
                      if (i) {
                        for (var c = 0; c < i.length; c++)
                          if (
                            ((n = i[c]),
                            n.getAttribute("href") ===
                              (a.href == null || a.href === "" ? null : a.href) &&
                              n.getAttribute("rel") === (a.rel == null ? null : a.rel) &&
                              n.getAttribute("title") === (a.title == null ? null : a.title) &&
                              n.getAttribute("crossorigin") ===
                                (a.crossOrigin == null ? null : a.crossOrigin))
                          ) {
                            i.splice(c, 1);
                            break t;
                          }
                      }
                      ((n = u.createElement(e)), Rl(n, e, a), u.head.appendChild(n));
                      break;
                    case "meta":
                      if ((i = fm("meta", "content", u).get(e + (a.content || "")))) {
                        for (c = 0; c < i.length; c++)
                          if (
                            ((n = i[c]),
                            n.getAttribute("content") ===
                              (a.content == null ? null : "" + a.content) &&
                              n.getAttribute("name") === (a.name == null ? null : a.name) &&
                              n.getAttribute("property") ===
                                (a.property == null ? null : a.property) &&
                              n.getAttribute("http-equiv") ===
                                (a.httpEquiv == null ? null : a.httpEquiv) &&
                              n.getAttribute("charset") === (a.charSet == null ? null : a.charSet))
                          ) {
                            i.splice(c, 1);
                            break t;
                          }
                      }
                      ((n = u.createElement(e)), Rl(n, e, a), u.head.appendChild(n));
                      break;
                    default:
                      throw Error(d(468, e));
                  }
                  ((n[Dl] = l), Ol(n), (e = n));
                }
                l.stateNode = e;
              } else sm(u, l.type, l.stateNode);
            else l.stateNode = cm(u, e, l.memoizedProps);
          else
            n !== e
              ? (n === null
                  ? a.stateNode !== null && ((a = a.stateNode), a.parentNode.removeChild(a))
                  : n.count--,
                e === null ? sm(u, l.type, l.stateNode) : cm(u, e, l.memoizedProps))
              : e === null && l.stateNode !== null && Ac(l, l.memoizedProps, a.memoizedProps);
        }
        break;
      case 27:
        (Jl(t, l),
          wl(l),
          e & 512 && (Al || a === null || Nt(a, a.return)),
          a !== null && e & 4 && Ac(l, l.memoizedProps, a.memoizedProps));
        break;
      case 5:
        if ((Jl(t, l), wl(l), e & 512 && (Al || a === null || Nt(a, a.return)), l.flags & 32)) {
          u = l.stateNode;
          try {
            le(u, "");
          } catch (M) {
            el(l, l.return, M);
          }
        }
        (e & 4 &&
          l.stateNode != null &&
          ((u = l.memoizedProps), Ac(l, u, a !== null ? a.memoizedProps : u)),
          e & 1024 && (Mc = !0));
        break;
      case 6:
        if ((Jl(t, l), wl(l), e & 4)) {
          if (l.stateNode === null) throw Error(d(162));
          ((e = l.memoizedProps), (a = l.stateNode));
          try {
            a.nodeValue = e;
          } catch (M) {
            el(l, l.return, M);
          }
        }
        break;
      case 3:
        if (
          ((Cn = null),
          (u = _t),
          (_t = Rn(t.containerInfo)),
          Jl(t, l),
          (_t = u),
          wl(l),
          e & 4 && a !== null && a.memoizedState.isDehydrated)
        )
          try {
            He(t.containerInfo);
          } catch (M) {
            el(l, l.return, M);
          }
        Mc && ((Mc = !1), s0(l));
        break;
      case 4:
        ((e = _t), (_t = Rn(l.stateNode.containerInfo)), Jl(t, l), wl(l), (_t = e));
        break;
      case 12:
        (Jl(t, l), wl(l));
        break;
      case 31:
        (Jl(t, l),
          wl(l),
          e & 4 && ((e = l.updateQueue), e !== null && ((l.updateQueue = null), bn(l, e))));
        break;
      case 13:
        (Jl(t, l),
          wl(l),
          l.child.flags & 8192 &&
            (l.memoizedState !== null) != (a !== null && a.memoizedState !== null) &&
            (_n = Il()),
          e & 4 && ((e = l.updateQueue), e !== null && ((l.updateQueue = null), bn(l, e))));
        break;
      case 22:
        u = l.memoizedState !== null;
        var f = a !== null && a.memoizedState !== null,
          y = Vt,
          g = Al;
        if (((Vt = y || u), (Al = g || f), Jl(t, l), (Al = g), (Vt = y), wl(l), e & 8192))
          l: for (
            t = l.stateNode,
              t._visibility = u ? t._visibility & -2 : t._visibility | 1,
              u && (a === null || f || Vt || Al || Qa(l)),
              a = null,
              t = l;
            ;
          ) {
            if (t.tag === 5 || t.tag === 26) {
              if (a === null) {
                f = a = t;
                try {
                  if (((n = f.stateNode), u))
                    ((i = n.style),
                      typeof i.setProperty == "function"
                        ? i.setProperty("display", "none", "important")
                        : (i.display = "none"));
                  else {
                    c = f.stateNode;
                    var _ = f.memoizedProps.style,
                      v = _ != null && _.hasOwnProperty("display") ? _.display : null;
                    c.style.display = v == null || typeof v == "boolean" ? "" : ("" + v).trim();
                  }
                } catch (M) {
                  el(f, f.return, M);
                }
              }
            } else if (t.tag === 6) {
              if (a === null) {
                f = t;
                try {
                  f.stateNode.nodeValue = u ? "" : f.memoizedProps;
                } catch (M) {
                  el(f, f.return, M);
                }
              }
            } else if (t.tag === 18) {
              if (a === null) {
                f = t;
                try {
                  var r = f.stateNode;
                  u ? I0(r, !0) : I0(f.stateNode, !1);
                } catch (M) {
                  el(f, f.return, M);
                }
              }
            } else if (
              ((t.tag !== 22 && t.tag !== 23) || t.memoizedState === null || t === l) &&
              t.child !== null
            ) {
              ((t.child.return = t), (t = t.child));
              continue;
            }
            if (t === l) break l;
            for (; t.sibling === null;) {
              if (t.return === null || t.return === l) break l;
              (a === t && (a = null), (t = t.return));
            }
            (a === t && (a = null), (t.sibling.return = t.return), (t = t.sibling));
          }
        e & 4 &&
          ((e = l.updateQueue),
          e !== null && ((a = e.retryQueue), a !== null && ((e.retryQueue = null), bn(l, a))));
        break;
      case 19:
        (Jl(t, l),
          wl(l),
          e & 4 && ((e = l.updateQueue), e !== null && ((l.updateQueue = null), bn(l, e))));
        break;
      case 30:
        break;
      case 21:
        break;
      default:
        (Jl(t, l), wl(l));
    }
  }
  function wl(l) {
    var t = l.flags;
    if (t & 2) {
      try {
        for (var a, e = l.return; e !== null;) {
          if (l0(e)) {
            a = e;
            break;
          }
          e = e.return;
        }
        if (a == null) throw Error(d(160));
        switch (a.tag) {
          case 27:
            var u = a.stateNode,
              n = pc(l);
            Sn(l, n, u);
            break;
          case 5:
            var i = a.stateNode;
            a.flags & 32 && (le(i, ""), (a.flags &= -33));
            var c = pc(l);
            Sn(l, c, i);
            break;
          case 3:
          case 4:
            var f = a.stateNode.containerInfo,
              y = pc(l);
            Oc(l, y, f);
            break;
          default:
            throw Error(d(161));
        }
      } catch (g) {
        el(l, l.return, g);
      }
      l.flags &= -3;
    }
    t & 4096 && (l.flags &= -4097);
  }
  function s0(l) {
    if (l.subtreeFlags & 1024)
      for (l = l.child; l !== null;) {
        var t = l;
        (s0(t), t.tag === 5 && t.flags & 1024 && t.stateNode.reset(), (l = l.sibling));
      }
  }
  function Kt(l, t) {
    if (t.subtreeFlags & 8772)
      for (t = t.child; t !== null;) (e0(l, t.alternate, t), (t = t.sibling));
  }
  function Qa(l) {
    for (l = l.child; l !== null;) {
      var t = l;
      switch (t.tag) {
        case 0:
        case 11:
        case 14:
        case 15:
          (oa(4, t, t.return), Qa(t));
          break;
        case 1:
          Nt(t, t.return);
          var a = t.stateNode;
          (typeof a.componentWillUnmount == "function" && Io(t, t.return, a), Qa(t));
          break;
        case 27:
          Su(t.stateNode);
        case 26:
        case 5:
          (Nt(t, t.return), Qa(t));
          break;
        case 22:
          t.memoizedState === null && Qa(t);
          break;
        case 30:
          Qa(t);
          break;
        default:
          Qa(t);
      }
      l = l.sibling;
    }
  }
  function Jt(l, t, a) {
    for (a = a && (t.subtreeFlags & 8772) !== 0, t = t.child; t !== null;) {
      var e = t.alternate,
        u = l,
        n = t,
        i = n.flags;
      switch (n.tag) {
        case 0:
        case 11:
        case 15:
          (Jt(u, n, a), fu(4, n));
          break;
        case 1:
          if ((Jt(u, n, a), (e = n), (u = e.stateNode), typeof u.componentDidMount == "function"))
            try {
              u.componentDidMount();
            } catch (y) {
              el(e, e.return, y);
            }
          if (((e = n), (u = e.updateQueue), u !== null)) {
            var c = e.stateNode;
            try {
              var f = u.shared.hiddenCallbacks;
              if (f !== null)
                for (u.shared.hiddenCallbacks = null, u = 0; u < f.length; u++) Gs(f[u], c);
            } catch (y) {
              el(e, e.return, y);
            }
          }
          (a && i & 64 && Fo(n), su(n, n.return));
          break;
        case 27:
          t0(n);
        case 26:
        case 5:
          (Jt(u, n, a), a && e === null && i & 4 && Po(n), su(n, n.return));
          break;
        case 12:
          Jt(u, n, a);
          break;
        case 31:
          (Jt(u, n, a), a && i & 4 && i0(u, n));
          break;
        case 13:
          (Jt(u, n, a), a && i & 4 && c0(u, n));
          break;
        case 22:
          (n.memoizedState === null && Jt(u, n, a), su(n, n.return));
          break;
        case 30:
          break;
        default:
          Jt(u, n, a);
      }
      t = t.sibling;
    }
  }
  function Nc(l, t) {
    var a = null;
    (l !== null &&
      l.memoizedState !== null &&
      l.memoizedState.cachePool !== null &&
      (a = l.memoizedState.cachePool.pool),
      (l = null),
      t.memoizedState !== null &&
        t.memoizedState.cachePool !== null &&
        (l = t.memoizedState.cachePool.pool),
      l !== a && (l != null && l.refCount++, a != null && $e(a)));
  }
  function Dc(l, t) {
    ((l = null),
      t.alternate !== null && (l = t.alternate.memoizedState.cache),
      (t = t.memoizedState.cache),
      t !== l && (t.refCount++, l != null && $e(l)));
  }
  function Tt(l, t, a, e) {
    if (t.subtreeFlags & 10256) for (t = t.child; t !== null;) (o0(l, t, a, e), (t = t.sibling));
  }
  function o0(l, t, a, e) {
    var u = t.flags;
    switch (t.tag) {
      case 0:
      case 11:
      case 15:
        (Tt(l, t, a, e), u & 2048 && fu(9, t));
        break;
      case 1:
        Tt(l, t, a, e);
        break;
      case 3:
        (Tt(l, t, a, e),
          u & 2048 &&
            ((l = null),
            t.alternate !== null && (l = t.alternate.memoizedState.cache),
            (t = t.memoizedState.cache),
            t !== l && (t.refCount++, l != null && $e(l))));
        break;
      case 12:
        if (u & 2048) {
          (Tt(l, t, a, e), (l = t.stateNode));
          try {
            var n = t.memoizedProps,
              i = n.id,
              c = n.onPostCommit;
            typeof c == "function" &&
              c(i, t.alternate === null ? "mount" : "update", l.passiveEffectDuration, -0);
          } catch (f) {
            el(t, t.return, f);
          }
        } else Tt(l, t, a, e);
        break;
      case 31:
        Tt(l, t, a, e);
        break;
      case 13:
        Tt(l, t, a, e);
        break;
      case 23:
        break;
      case 22:
        ((n = t.stateNode),
          (i = t.alternate),
          t.memoizedState !== null
            ? n._visibility & 2
              ? Tt(l, t, a, e)
              : ou(l, t)
            : n._visibility & 2
              ? Tt(l, t, a, e)
              : ((n._visibility |= 2), ze(l, t, a, e, (t.subtreeFlags & 10256) !== 0 || !1)),
          u & 2048 && Nc(i, t));
        break;
      case 24:
        (Tt(l, t, a, e), u & 2048 && Dc(t.alternate, t));
        break;
      default:
        Tt(l, t, a, e);
    }
  }
  function ze(l, t, a, e, u) {
    for (u = u && ((t.subtreeFlags & 10256) !== 0 || !1), t = t.child; t !== null;) {
      var n = l,
        i = t,
        c = a,
        f = e,
        y = i.flags;
      switch (i.tag) {
        case 0:
        case 11:
        case 15:
          (ze(n, i, c, f, u), fu(8, i));
          break;
        case 23:
          break;
        case 22:
          var g = i.stateNode;
          (i.memoizedState !== null
            ? g._visibility & 2
              ? ze(n, i, c, f, u)
              : ou(n, i)
            : ((g._visibility |= 2), ze(n, i, c, f, u)),
            u && y & 2048 && Nc(i.alternate, i));
          break;
        case 24:
          (ze(n, i, c, f, u), u && y & 2048 && Dc(i.alternate, i));
          break;
        default:
          ze(n, i, c, f, u);
      }
      t = t.sibling;
    }
  }
  function ou(l, t) {
    if (t.subtreeFlags & 10256)
      for (t = t.child; t !== null;) {
        var a = l,
          e = t,
          u = e.flags;
        switch (e.tag) {
          case 22:
            (ou(a, e), u & 2048 && Nc(e.alternate, e));
            break;
          case 24:
            (ou(a, e), u & 2048 && Dc(e.alternate, e));
            break;
          default:
            ou(a, e);
        }
        t = t.sibling;
      }
  }
  var mu = 8192;
  function _e(l, t, a) {
    if (l.subtreeFlags & mu) for (l = l.child; l !== null;) (m0(l, t, a), (l = l.sibling));
  }
  function m0(l, t, a) {
    switch (l.tag) {
      case 26:
        (_e(l, t, a),
          l.flags & mu && l.memoizedState !== null && Ph(a, _t, l.memoizedState, l.memoizedProps));
        break;
      case 5:
        _e(l, t, a);
        break;
      case 3:
      case 4:
        var e = _t;
        ((_t = Rn(l.stateNode.containerInfo)), _e(l, t, a), (_t = e));
        break;
      case 22:
        l.memoizedState === null &&
          ((e = l.alternate),
          e !== null && e.memoizedState !== null
            ? ((e = mu), (mu = 16777216), _e(l, t, a), (mu = e))
            : _e(l, t, a));
        break;
      default:
        _e(l, t, a);
    }
  }
  function d0(l) {
    var t = l.alternate;
    if (t !== null && ((l = t.child), l !== null)) {
      t.child = null;
      do ((t = l.sibling), (l.sibling = null), (l = t));
      while (l !== null);
    }
  }
  function du(l) {
    var t = l.deletions;
    if ((l.flags & 16) !== 0) {
      if (t !== null)
        for (var a = 0; a < t.length; a++) {
          var e = t[a];
          ((Ml = e), y0(e, l));
        }
      d0(l);
    }
    if (l.subtreeFlags & 10256) for (l = l.child; l !== null;) (h0(l), (l = l.sibling));
  }
  function h0(l) {
    switch (l.tag) {
      case 0:
      case 11:
      case 15:
        (du(l), l.flags & 2048 && oa(9, l, l.return));
        break;
      case 3:
        du(l);
        break;
      case 12:
        du(l);
        break;
      case 22:
        var t = l.stateNode;
        l.memoizedState !== null && t._visibility & 2 && (l.return === null || l.return.tag !== 13)
          ? ((t._visibility &= -3), zn(l))
          : du(l);
        break;
      default:
        du(l);
    }
  }
  function zn(l) {
    var t = l.deletions;
    if ((l.flags & 16) !== 0) {
      if (t !== null)
        for (var a = 0; a < t.length; a++) {
          var e = t[a];
          ((Ml = e), y0(e, l));
        }
      d0(l);
    }
    for (l = l.child; l !== null;) {
      switch (((t = l), t.tag)) {
        case 0:
        case 11:
        case 15:
          (oa(8, t, t.return), zn(t));
          break;
        case 22:
          ((a = t.stateNode), a._visibility & 2 && ((a._visibility &= -3), zn(t)));
          break;
        default:
          zn(t);
      }
      l = l.sibling;
    }
  }
  function y0(l, t) {
    for (; Ml !== null;) {
      var a = Ml;
      switch (a.tag) {
        case 0:
        case 11:
        case 15:
          oa(8, a, t);
          break;
        case 23:
        case 22:
          if (a.memoizedState !== null && a.memoizedState.cachePool !== null) {
            var e = a.memoizedState.cachePool.pool;
            e != null && e.refCount++;
          }
          break;
        case 24:
          $e(a.memoizedState.cache);
      }
      if (((e = a.child), e !== null)) ((e.return = a), (Ml = e));
      else
        l: for (a = l; Ml !== null;) {
          e = Ml;
          var u = e.sibling,
            n = e.return;
          if ((u0(e), e === a)) {
            Ml = null;
            break l;
          }
          if (u !== null) {
            ((u.return = n), (Ml = u));
            break l;
          }
          Ml = n;
        }
    }
  }
  var yh = {
      getCacheForType: function (l) {
        var t = Hl(_l),
          a = t.data.get(l);
        return (a === void 0 && ((a = l()), t.data.set(l, a)), a);
      },
      cacheSignal: function () {
        return Hl(_l).controller.signal;
      },
    },
    vh = typeof WeakMap == "function" ? WeakMap : Map,
    P = 0,
    sl = null,
    K = null,
    w = 0,
    al = 0,
    nt = null,
    ma = !1,
    Te = !1,
    Uc = !1,
    wt = 0,
    gl = 0,
    da = 0,
    Za = 0,
    Hc = 0,
    it = 0,
    Ee = 0,
    hu = null,
    Wl = null,
    jc = !1,
    _n = 0,
    v0 = 0,
    Tn = 1 / 0,
    En = null,
    ha = null,
    pl = 0,
    ya = null,
    Ae = null,
    Wt = 0,
    Rc = 0,
    xc = null,
    r0 = null,
    yu = 0,
    Cc = null;
  function ct() {
    return (P & 2) !== 0 && w !== 0 ? w & -w : S.T !== null ? Qc() : Hf();
  }
  function g0() {
    if (it === 0)
      if ((w & 536870912) === 0 || k) {
        var l = Uu;
        ((Uu <<= 1), (Uu & 3932160) === 0 && (Uu = 262144), (it = l));
      } else it = 536870912;
    return ((l = et.current), l !== null && (l.flags |= 32), it);
  }
  function $l(l, t, a) {
    (((l === sl && (al === 2 || al === 9)) || l.cancelPendingCommit !== null) &&
      (pe(l, 0), va(l, w, it, !1)),
      Ce(l, a),
      ((P & 2) === 0 || l !== sl) &&
        (l === sl && ((P & 2) === 0 && (Za |= a), gl === 4 && va(l, w, it, !1)), Dt(l)));
  }
  function S0(l, t, a) {
    if ((P & 6) !== 0) throw Error(d(327));
    var e = (!a && (t & 127) === 0 && (t & l.expiredLanes) === 0) || xe(l, t),
      u = e ? Sh(l, t) : Bc(l, t, !0),
      n = e;
    do {
      if (u === 0) {
        Te && !e && va(l, t, 0, !1);
        break;
      } else {
        if (((a = l.current.alternate), n && !rh(a))) {
          ((u = Bc(l, t, !1)), (n = !1));
          continue;
        }
        if (u === 2) {
          if (((n = t), l.errorRecoveryDisabledLanes & n)) var i = 0;
          else
            ((i = l.pendingLanes & -536870913), (i = i !== 0 ? i : i & 536870912 ? 536870912 : 0));
          if (i !== 0) {
            t = i;
            l: {
              var c = l;
              u = hu;
              var f = c.current.memoizedState.isDehydrated;
              if ((f && (pe(c, i).flags |= 256), (i = Bc(c, i, !1)), i !== 2)) {
                if (Uc && !f) {
                  ((c.errorRecoveryDisabledLanes |= n), (Za |= n), (u = 4));
                  break l;
                }
                ((n = Wl), (Wl = u), n !== null && (Wl === null ? (Wl = n) : Wl.push.apply(Wl, n)));
              }
              u = i;
            }
            if (((n = !1), u !== 2)) continue;
          }
        }
        if (u === 1) {
          (pe(l, 0), va(l, t, 0, !0));
          break;
        }
        l: {
          switch (((e = l), (n = u), n)) {
            case 0:
            case 1:
              throw Error(d(345));
            case 4:
              if ((t & 4194048) !== t) break;
            case 6:
              va(e, t, it, !ma);
              break l;
            case 2:
              Wl = null;
              break;
            case 3:
            case 5:
              break;
            default:
              throw Error(d(329));
          }
          if ((t & 62914560) === t && ((u = _n + 300 - Il()), 10 < u)) {
            if ((va(e, t, it, !ma), ju(e, 0, !0) !== 0)) break l;
            ((Wt = t),
              (e.timeoutHandle = $0(
                b0.bind(null, e, a, Wl, En, jc, t, it, Za, Ee, ma, n, "Throttled", -0, 0),
                u,
              )));
            break l;
          }
          b0(e, a, Wl, En, jc, t, it, Za, Ee, ma, n, null, -0, 0);
        }
      }
      break;
    } while (!0);
    Dt(l);
  }
  function b0(l, t, a, e, u, n, i, c, f, y, g, _, v, r) {
    if (((l.timeoutHandle = -1), (_ = t.subtreeFlags), _ & 8192 || (_ & 16785408) === 16785408)) {
      ((_ = {
        stylesheets: null,
        count: 0,
        imgCount: 0,
        imgBytes: 0,
        suspenseyImages: [],
        waitingForImages: !0,
        waitingForViewTransition: !1,
        unsuspend: Rt,
      }),
        m0(t, n, _));
      var M = (n & 62914560) === n ? _n - Il() : (n & 4194048) === n ? v0 - Il() : 0;
      if (((M = ly(_, M)), M !== null)) {
        ((Wt = n),
          (l.cancelPendingCommit = M(M0.bind(null, l, t, n, a, e, u, i, c, f, g, _, null, v, r))),
          va(l, n, i, !y));
        return;
      }
    }
    M0(l, t, n, a, e, u, i, c, f);
  }
  function rh(l) {
    for (var t = l; ;) {
      var a = t.tag;
      if (
        (a === 0 || a === 11 || a === 15) &&
        t.flags & 16384 &&
        ((a = t.updateQueue), a !== null && ((a = a.stores), a !== null))
      )
        for (var e = 0; e < a.length; e++) {
          var u = a[e],
            n = u.getSnapshot;
          u = u.value;
          try {
            if (!tt(n(), u)) return !1;
          } catch {
            return !1;
          }
        }
      if (((a = t.child), t.subtreeFlags & 16384 && a !== null)) ((a.return = t), (t = a));
      else {
        if (t === l) break;
        for (; t.sibling === null;) {
          if (t.return === null || t.return === l) return !0;
          t = t.return;
        }
        ((t.sibling.return = t.return), (t = t.sibling));
      }
    }
    return !0;
  }
  function va(l, t, a, e) {
    ((t &= ~Hc),
      (t &= ~Za),
      (l.suspendedLanes |= t),
      (l.pingedLanes &= ~t),
      e && (l.warmLanes |= t),
      (e = l.expirationTimes));
    for (var u = t; 0 < u;) {
      var n = 31 - lt(u),
        i = 1 << n;
      ((e[n] = -1), (u &= ~i));
    }
    a !== 0 && Nf(l, a, t);
  }
  function An() {
    return (P & 6) === 0 ? (vu(0), !1) : !0;
  }
  function qc() {
    if (K !== null) {
      if (al === 0) var l = K.return;
      else ((l = K), (Bt = Ra = null), Ii(l), (ve = null), (Fe = 0), (l = K));
      for (; l !== null;) (ko(l.alternate, l), (l = l.return));
      K = null;
    }
  }
  function pe(l, t) {
    var a = l.timeoutHandle;
    (a !== -1 && ((l.timeoutHandle = -1), qh(a)),
      (a = l.cancelPendingCommit),
      a !== null && ((l.cancelPendingCommit = null), a()),
      (Wt = 0),
      qc(),
      (sl = l),
      (K = a = Ct(l.current, null)),
      (w = t),
      (al = 0),
      (nt = null),
      (ma = !1),
      (Te = xe(l, t)),
      (Uc = !1),
      (Ee = it = Hc = Za = da = gl = 0),
      (Wl = hu = null),
      (jc = !1),
      (t & 8) !== 0 && (t |= t & 32));
    var e = l.entangledLanes;
    if (e !== 0)
      for (l = l.entanglements, e &= t; 0 < e;) {
        var u = 31 - lt(e),
          n = 1 << u;
        ((t |= l[u]), (e &= ~n));
      }
    return ((wt = t), Lu(), a);
  }
  function z0(l, t) {
    ((Q = null),
      (S.H = nu),
      t === ye || t === Iu
        ? ((t = Cs()), (al = 3))
        : t === Xi
          ? ((t = Cs()), (al = 4))
          : (al =
              t === yc
                ? 8
                : t !== null && typeof t == "object" && typeof t.then == "function"
                  ? 6
                  : 1),
      (nt = t),
      K === null && ((gl = 1), hn(l, dt(t, l.current))));
  }
  function _0() {
    var l = et.current;
    return l === null
      ? !0
      : (w & 4194048) === w
        ? rt === null
        : (w & 62914560) === w || (w & 536870912) !== 0
          ? l === rt
          : !1;
  }
  function T0() {
    var l = S.H;
    return ((S.H = nu), l === null ? nu : l);
  }
  function E0() {
    var l = S.A;
    return ((S.A = yh), l);
  }
  function pn() {
    ((gl = 4),
      ma || ((w & 4194048) !== w && et.current !== null) || (Te = !0),
      ((da & 134217727) === 0 && (Za & 134217727) === 0) || sl === null || va(sl, w, it, !1));
  }
  function Bc(l, t, a) {
    var e = P;
    P |= 2;
    var u = T0(),
      n = E0();
    ((sl !== l || w !== t) && ((En = null), pe(l, t)), (t = !1));
    var i = gl;
    l: do
      try {
        if (al !== 0 && K !== null) {
          var c = K,
            f = nt;
          switch (al) {
            case 8:
              (qc(), (i = 6));
              break l;
            case 3:
            case 2:
            case 9:
            case 6:
              et.current === null && (t = !0);
              var y = al;
              if (((al = 0), (nt = null), Oe(l, c, f, y), a && Te)) {
                i = 0;
                break l;
              }
              break;
            default:
              ((y = al), (al = 0), (nt = null), Oe(l, c, f, y));
          }
        }
        (gh(), (i = gl));
        break;
      } catch (g) {
        z0(l, g);
      }
    while (!0);
    return (
      t && l.shellSuspendCounter++,
      (Bt = Ra = null),
      (P = e),
      (S.H = u),
      (S.A = n),
      K === null && ((sl = null), (w = 0), Lu()),
      i
    );
  }
  function gh() {
    for (; K !== null;) A0(K);
  }
  function Sh(l, t) {
    var a = P;
    P |= 2;
    var e = T0(),
      u = E0();
    sl !== l || w !== t ? ((En = null), (Tn = Il() + 500), pe(l, t)) : (Te = xe(l, t));
    l: do
      try {
        if (al !== 0 && K !== null) {
          t = K;
          var n = nt;
          t: switch (al) {
            case 1:
              ((al = 0), (nt = null), Oe(l, t, n, 1));
              break;
            case 2:
            case 9:
              if (Rs(n)) {
                ((al = 0), (nt = null), p0(t));
                break;
              }
              ((t = function () {
                ((al !== 2 && al !== 9) || sl !== l || (al = 7), Dt(l));
              }),
                n.then(t, t));
              break l;
            case 3:
              al = 7;
              break l;
            case 4:
              al = 5;
              break l;
            case 7:
              Rs(n) ? ((al = 0), (nt = null), p0(t)) : ((al = 0), (nt = null), Oe(l, t, n, 7));
              break;
            case 5:
              var i = null;
              switch (K.tag) {
                case 26:
                  i = K.memoizedState;
                case 5:
                case 27:
                  var c = K;
                  if (i ? om(i) : c.stateNode.complete) {
                    ((al = 0), (nt = null));
                    var f = c.sibling;
                    if (f !== null) K = f;
                    else {
                      var y = c.return;
                      y !== null ? ((K = y), On(y)) : (K = null);
                    }
                    break t;
                  }
              }
              ((al = 0), (nt = null), Oe(l, t, n, 5));
              break;
            case 6:
              ((al = 0), (nt = null), Oe(l, t, n, 6));
              break;
            case 8:
              (qc(), (gl = 6));
              break l;
            default:
              throw Error(d(462));
          }
        }
        bh();
        break;
      } catch (g) {
        z0(l, g);
      }
    while (!0);
    return (
      (Bt = Ra = null),
      (S.H = e),
      (S.A = u),
      (P = a),
      K !== null ? 0 : ((sl = null), (w = 0), Lu(), gl)
    );
  }
  function bh() {
    for (; K !== null && !Zm();) A0(K);
  }
  function A0(l) {
    var t = Wo(l.alternate, l, wt);
    ((l.memoizedProps = l.pendingProps), t === null ? On(l) : (K = t));
  }
  function p0(l) {
    var t = l,
      a = t.alternate;
    switch (t.tag) {
      case 15:
      case 0:
        t = Zo(a, t, t.pendingProps, t.type, void 0, w);
        break;
      case 11:
        t = Zo(a, t, t.pendingProps, t.type.render, t.ref, w);
        break;
      case 5:
        Ii(t);
      default:
        (ko(a, t), (t = K = Ts(t, wt)), (t = Wo(a, t, wt)));
    }
    ((l.memoizedProps = l.pendingProps), t === null ? On(l) : (K = t));
  }
  function Oe(l, t, a, e) {
    ((Bt = Ra = null), Ii(t), (ve = null), (Fe = 0));
    var u = t.return;
    try {
      if (ch(l, u, t, a, w)) {
        ((gl = 1), hn(l, dt(a, l.current)), (K = null));
        return;
      }
    } catch (n) {
      if (u !== null) throw ((K = u), n);
      ((gl = 1), hn(l, dt(a, l.current)), (K = null));
      return;
    }
    t.flags & 32768
      ? (k || e === 1
          ? (l = !0)
          : Te || (w & 536870912) !== 0
            ? (l = !1)
            : ((ma = l = !0),
              (e === 2 || e === 9 || e === 3 || e === 6) &&
                ((e = et.current), e !== null && e.tag === 13 && (e.flags |= 16384))),
        O0(t, l))
      : On(t);
  }
  function On(l) {
    var t = l;
    do {
      if ((t.flags & 32768) !== 0) {
        O0(t, ma);
        return;
      }
      l = t.return;
      var a = oh(t.alternate, t, wt);
      if (a !== null) {
        K = a;
        return;
      }
      if (((t = t.sibling), t !== null)) {
        K = t;
        return;
      }
      K = t = l;
    } while (t !== null);
    gl === 0 && (gl = 5);
  }
  function O0(l, t) {
    do {
      var a = mh(l.alternate, l);
      if (a !== null) {
        ((a.flags &= 32767), (K = a));
        return;
      }
      if (
        ((a = l.return),
        a !== null && ((a.flags |= 32768), (a.subtreeFlags = 0), (a.deletions = null)),
        !t && ((l = l.sibling), l !== null))
      ) {
        K = l;
        return;
      }
      K = l = a;
    } while (l !== null);
    ((gl = 6), (K = null));
  }
  function M0(l, t, a, e, u, n, i, c, f) {
    l.cancelPendingCommit = null;
    do Mn();
    while (pl !== 0);
    if ((P & 6) !== 0) throw Error(d(327));
    if (t !== null) {
      if (t === l.current) throw Error(d(177));
      if (
        ((n = t.lanes | t.childLanes),
        (n |= pi),
        Im(l, a, n, i, c, f),
        l === sl && ((K = sl = null), (w = 0)),
        (Ae = t),
        (ya = l),
        (Wt = a),
        (Rc = n),
        (xc = u),
        (r0 = e),
        (t.subtreeFlags & 10256) !== 0 || (t.flags & 10256) !== 0
          ? ((l.callbackNode = null),
            (l.callbackPriority = 0),
            Eh(Nu, function () {
              return (j0(), null);
            }))
          : ((l.callbackNode = null), (l.callbackPriority = 0)),
        (e = (t.flags & 13878) !== 0),
        (t.subtreeFlags & 13878) !== 0 || e)
      ) {
        ((e = S.T), (S.T = null), (u = p.p), (p.p = 2), (i = P), (P |= 4));
        try {
          dh(l, t, a);
        } finally {
          ((P = i), (p.p = u), (S.T = e));
        }
      }
      ((pl = 1), N0(), D0(), U0());
    }
  }
  function N0() {
    if (pl === 1) {
      pl = 0;
      var l = ya,
        t = Ae,
        a = (t.flags & 13878) !== 0;
      if ((t.subtreeFlags & 13878) !== 0 || a) {
        ((a = S.T), (S.T = null));
        var e = p.p;
        p.p = 2;
        var u = P;
        P |= 4;
        try {
          f0(t, l);
          var n = $c,
            i = hs(l.containerInfo),
            c = n.focusedElem,
            f = n.selectionRange;
          if (i !== c && c && c.ownerDocument && ds(c.ownerDocument.documentElement, c)) {
            if (f !== null && zi(c)) {
              var y = f.start,
                g = f.end;
              if ((g === void 0 && (g = y), "selectionStart" in c))
                ((c.selectionStart = y), (c.selectionEnd = Math.min(g, c.value.length)));
              else {
                var _ = c.ownerDocument || document,
                  v = (_ && _.defaultView) || window;
                if (v.getSelection) {
                  var r = v.getSelection(),
                    M = c.textContent.length,
                    C = Math.min(f.start, M),
                    cl = f.end === void 0 ? C : Math.min(f.end, M);
                  !r.extend && C > cl && ((i = cl), (cl = C), (C = i));
                  var m = ms(c, C),
                    s = ms(c, cl);
                  if (
                    m &&
                    s &&
                    (r.rangeCount !== 1 ||
                      r.anchorNode !== m.node ||
                      r.anchorOffset !== m.offset ||
                      r.focusNode !== s.node ||
                      r.focusOffset !== s.offset)
                  ) {
                    var h = _.createRange();
                    (h.setStart(m.node, m.offset),
                      r.removeAllRanges(),
                      C > cl
                        ? (r.addRange(h), r.extend(s.node, s.offset))
                        : (h.setEnd(s.node, s.offset), r.addRange(h)));
                  }
                }
              }
            }
            for (_ = [], r = c; (r = r.parentNode);)
              r.nodeType === 1 && _.push({ element: r, left: r.scrollLeft, top: r.scrollTop });
            for (typeof c.focus == "function" && c.focus(), c = 0; c < _.length; c++) {
              var z = _[c];
              ((z.element.scrollLeft = z.left), (z.element.scrollTop = z.top));
            }
          }
          ((Gn = !!Wc), ($c = Wc = null));
        } finally {
          ((P = u), (p.p = e), (S.T = a));
        }
      }
      ((l.current = t), (pl = 2));
    }
  }
  function D0() {
    if (pl === 2) {
      pl = 0;
      var l = ya,
        t = Ae,
        a = (t.flags & 8772) !== 0;
      if ((t.subtreeFlags & 8772) !== 0 || a) {
        ((a = S.T), (S.T = null));
        var e = p.p;
        p.p = 2;
        var u = P;
        P |= 4;
        try {
          e0(l, t.alternate, t);
        } finally {
          ((P = u), (p.p = e), (S.T = a));
        }
      }
      pl = 3;
    }
  }
  function U0() {
    if (pl === 4 || pl === 3) {
      ((pl = 0), Vm());
      var l = ya,
        t = Ae,
        a = Wt,
        e = r0;
      (t.subtreeFlags & 10256) !== 0 || (t.flags & 10256) !== 0
        ? (pl = 5)
        : ((pl = 0), (Ae = ya = null), H0(l, l.pendingLanes));
      var u = l.pendingLanes;
      if (
        (u === 0 && (ha = null),
        ti(a),
        (t = t.stateNode),
        Pl && typeof Pl.onCommitFiberRoot == "function")
      )
        try {
          Pl.onCommitFiberRoot(Re, t, void 0, (t.current.flags & 128) === 128);
        } catch {}
      if (e !== null) {
        ((t = S.T), (u = p.p), (p.p = 2), (S.T = null));
        try {
          for (var n = l.onRecoverableError, i = 0; i < e.length; i++) {
            var c = e[i];
            n(c.value, { componentStack: c.stack });
          }
        } finally {
          ((S.T = t), (p.p = u));
        }
      }
      ((Wt & 3) !== 0 && Mn(),
        Dt(l),
        (u = l.pendingLanes),
        (a & 261930) !== 0 && (u & 42) !== 0 ? (l === Cc ? yu++ : ((yu = 0), (Cc = l))) : (yu = 0),
        vu(0));
    }
  }
  function H0(l, t) {
    (l.pooledCacheLanes &= t) === 0 &&
      ((t = l.pooledCache), t != null && ((l.pooledCache = null), $e(t)));
  }
  function Mn() {
    return (N0(), D0(), U0(), j0());
  }
  function j0() {
    if (pl !== 5) return !1;
    var l = ya,
      t = Rc;
    Rc = 0;
    var a = ti(Wt),
      e = S.T,
      u = p.p;
    try {
      ((p.p = 32 > a ? 32 : a), (S.T = null), (a = xc), (xc = null));
      var n = ya,
        i = Wt;
      if (((pl = 0), (Ae = ya = null), (Wt = 0), (P & 6) !== 0)) throw Error(d(331));
      var c = P;
      if (
        ((P |= 4),
        h0(n.current),
        o0(n, n.current, i, a),
        (P = c),
        vu(0, !1),
        Pl && typeof Pl.onPostCommitFiberRoot == "function")
      )
        try {
          Pl.onPostCommitFiberRoot(Re, n);
        } catch {}
      return !0;
    } finally {
      ((p.p = u), (S.T = e), H0(l, t));
    }
  }
  function R0(l, t, a) {
    ((t = dt(a, t)),
      (t = hc(l.stateNode, t, 2)),
      (l = ca(l, t, 2)),
      l !== null && (Ce(l, 2), Dt(l)));
  }
  function el(l, t, a) {
    if (l.tag === 3) R0(l, l, a);
    else
      for (; t !== null;) {
        if (t.tag === 3) {
          R0(t, l, a);
          break;
        } else if (t.tag === 1) {
          var e = t.stateNode;
          if (
            typeof t.type.getDerivedStateFromError == "function" ||
            (typeof e.componentDidCatch == "function" && (ha === null || !ha.has(e)))
          ) {
            ((l = dt(a, l)),
              (a = xo(2)),
              (e = ca(t, a, 2)),
              e !== null && (Co(a, e, t, l), Ce(e, 2), Dt(e)));
            break;
          }
        }
        t = t.return;
      }
  }
  function Yc(l, t, a) {
    var e = l.pingCache;
    if (e === null) {
      e = l.pingCache = new vh();
      var u = new Set();
      e.set(t, u);
    } else ((u = e.get(t)), u === void 0 && ((u = new Set()), e.set(t, u)));
    u.has(a) || ((Uc = !0), u.add(a), (l = zh.bind(null, l, t, a)), t.then(l, l));
  }
  function zh(l, t, a) {
    var e = l.pingCache;
    (e !== null && e.delete(t),
      (l.pingedLanes |= l.suspendedLanes & a),
      (l.warmLanes &= ~a),
      sl === l &&
        (w & a) === a &&
        (gl === 4 || (gl === 3 && (w & 62914560) === w && 300 > Il() - _n)
          ? (P & 2) === 0 && pe(l, 0)
          : (Hc |= a),
        Ee === w && (Ee = 0)),
      Dt(l));
  }
  function x0(l, t) {
    (t === 0 && (t = Mf()), (l = Ua(l, t)), l !== null && (Ce(l, t), Dt(l)));
  }
  function _h(l) {
    var t = l.memoizedState,
      a = 0;
    (t !== null && (a = t.retryLane), x0(l, a));
  }
  function Th(l, t) {
    var a = 0;
    switch (l.tag) {
      case 31:
      case 13:
        var e = l.stateNode,
          u = l.memoizedState;
        u !== null && (a = u.retryLane);
        break;
      case 19:
        e = l.stateNode;
        break;
      case 22:
        e = l.stateNode._retryCache;
        break;
      default:
        throw Error(d(314));
    }
    (e !== null && e.delete(t), x0(l, a));
  }
  function Eh(l, t) {
    return Fn(l, t);
  }
  var Nn = null,
    Me = null,
    Gc = !1,
    Dn = !1,
    Xc = !1,
    ra = 0;
  function Dt(l) {
    (l !== Me && l.next === null && (Me === null ? (Nn = Me = l) : (Me = Me.next = l)),
      (Dn = !0),
      Gc || ((Gc = !0), ph()));
  }
  function vu(l, t) {
    if (!Xc && Dn) {
      Xc = !0;
      do
        for (var a = !1, e = Nn; e !== null;) {
          if (l !== 0) {
            var u = e.pendingLanes;
            if (u === 0) var n = 0;
            else {
              var i = e.suspendedLanes,
                c = e.pingedLanes;
              ((n = (1 << (31 - lt(42 | l) + 1)) - 1),
                (n &= u & ~(i & ~c)),
                (n = n & 201326741 ? (n & 201326741) | 1 : n ? n | 2 : 0));
            }
            n !== 0 && ((a = !0), Y0(e, n));
          } else
            ((n = w),
              (n = ju(
                e,
                e === sl ? n : 0,
                e.cancelPendingCommit !== null || e.timeoutHandle !== -1,
              )),
              (n & 3) === 0 || xe(e, n) || ((a = !0), Y0(e, n)));
          e = e.next;
        }
      while (a);
      Xc = !1;
    }
  }
  function Ah() {
    C0();
  }
  function C0() {
    Dn = Gc = !1;
    var l = 0;
    ra !== 0 && Ch() && (l = ra);
    for (var t = Il(), a = null, e = Nn; e !== null;) {
      var u = e.next,
        n = q0(e, t);
      (n === 0
        ? ((e.next = null), a === null ? (Nn = u) : (a.next = u), u === null && (Me = a))
        : ((a = e), (l !== 0 || (n & 3) !== 0) && (Dn = !0)),
        (e = u));
    }
    ((pl !== 0 && pl !== 5) || vu(l), ra !== 0 && (ra = 0));
  }
  function q0(l, t) {
    for (
      var a = l.suspendedLanes,
        e = l.pingedLanes,
        u = l.expirationTimes,
        n = l.pendingLanes & -62914561;
      0 < n;
    ) {
      var i = 31 - lt(n),
        c = 1 << i,
        f = u[i];
      (f === -1
        ? ((c & a) === 0 || (c & e) !== 0) && (u[i] = Fm(c, t))
        : f <= t && (l.expiredLanes |= c),
        (n &= ~c));
    }
    if (
      ((t = sl),
      (a = w),
      (a = ju(l, l === t ? a : 0, l.cancelPendingCommit !== null || l.timeoutHandle !== -1)),
      (e = l.callbackNode),
      a === 0 || (l === t && (al === 2 || al === 9)) || l.cancelPendingCommit !== null)
    )
      return (e !== null && e !== null && In(e), (l.callbackNode = null), (l.callbackPriority = 0));
    if ((a & 3) === 0 || xe(l, a)) {
      if (((t = a & -a), t === l.callbackPriority)) return t;
      switch ((e !== null && In(e), ti(a))) {
        case 2:
        case 8:
          a = pf;
          break;
        case 32:
          a = Nu;
          break;
        case 268435456:
          a = Of;
          break;
        default:
          a = Nu;
      }
      return (
        (e = B0.bind(null, l)),
        (a = Fn(a, e)),
        (l.callbackPriority = t),
        (l.callbackNode = a),
        t
      );
    }
    return (
      e !== null && e !== null && In(e),
      (l.callbackPriority = 2),
      (l.callbackNode = null),
      2
    );
  }
  function B0(l, t) {
    if (pl !== 0 && pl !== 5) return ((l.callbackNode = null), (l.callbackPriority = 0), null);
    var a = l.callbackNode;
    if (Mn() && l.callbackNode !== a) return null;
    var e = w;
    return (
      (e = ju(l, l === sl ? e : 0, l.cancelPendingCommit !== null || l.timeoutHandle !== -1)),
      e === 0
        ? null
        : (S0(l, e, t),
          q0(l, Il()),
          l.callbackNode != null && l.callbackNode === a ? B0.bind(null, l) : null)
    );
  }
  function Y0(l, t) {
    if (Mn()) return null;
    S0(l, t, !0);
  }
  function ph() {
    Bh(function () {
      (P & 6) !== 0 ? Fn(Af, Ah) : C0();
    });
  }
  function Qc() {
    if (ra === 0) {
      var l = de;
      (l === 0 && ((l = Du), (Du <<= 1), (Du & 261888) === 0 && (Du = 256)), (ra = l));
    }
    return ra;
  }
  function G0(l) {
    return l == null || typeof l == "symbol" || typeof l == "boolean"
      ? null
      : typeof l == "function"
        ? l
        : qu("" + l);
  }
  function X0(l, t) {
    var a = t.ownerDocument.createElement("input");
    return (
      (a.name = t.name),
      (a.value = t.value),
      l.id && a.setAttribute("form", l.id),
      t.parentNode.insertBefore(a, t),
      (l = new FormData(l)),
      a.parentNode.removeChild(a),
      l
    );
  }
  function Oh(l, t, a, e, u) {
    if (t === "submit" && a && a.stateNode === u) {
      var n = G0((u[Vl] || null).action),
        i = e.submitter;
      i &&
        ((t = (t = i[Vl] || null) ? G0(t.formAction) : i.getAttribute("formAction")),
        t !== null && ((n = t), (i = null)));
      var c = new Xu("action", "action", null, e, u);
      l.push({
        event: c,
        listeners: [
          {
            instance: null,
            listener: function () {
              if (e.defaultPrevented) {
                if (ra !== 0) {
                  var f = i ? X0(u, i) : new FormData(u);
                  cc(a, { pending: !0, data: f, method: u.method, action: n }, null, f);
                }
              } else
                typeof n == "function" &&
                  (c.preventDefault(),
                  (f = i ? X0(u, i) : new FormData(u)),
                  cc(a, { pending: !0, data: f, method: u.method, action: n }, n, f));
            },
            currentTarget: u,
          },
        ],
      });
    }
  }
  for (var Zc = 0; Zc < Ai.length; Zc++) {
    var Vc = Ai[Zc],
      Mh = Vc.toLowerCase(),
      Nh = Vc[0].toUpperCase() + Vc.slice(1);
    zt(Mh, "on" + Nh);
  }
  (zt(rs, "onAnimationEnd"),
    zt(gs, "onAnimationIteration"),
    zt(Ss, "onAnimationStart"),
    zt("dblclick", "onDoubleClick"),
    zt("focusin", "onFocus"),
    zt("focusout", "onBlur"),
    zt(Ld, "onTransitionRun"),
    zt(Kd, "onTransitionStart"),
    zt(Jd, "onTransitionCancel"),
    zt(bs, "onTransitionEnd"),
    Ia("onMouseEnter", ["mouseout", "mouseover"]),
    Ia("onMouseLeave", ["mouseout", "mouseover"]),
    Ia("onPointerEnter", ["pointerout", "pointerover"]),
    Ia("onPointerLeave", ["pointerout", "pointerover"]),
    Oa("onChange", "change click focusin focusout input keydown keyup selectionchange".split(" ")),
    Oa(
      "onSelect",
      "focusout contextmenu dragend focusin keydown keyup mousedown mouseup selectionchange".split(
        " ",
      ),
    ),
    Oa("onBeforeInput", ["compositionend", "keypress", "textInput", "paste"]),
    Oa("onCompositionEnd", "compositionend focusout keydown keypress keyup mousedown".split(" ")),
    Oa(
      "onCompositionStart",
      "compositionstart focusout keydown keypress keyup mousedown".split(" "),
    ),
    Oa(
      "onCompositionUpdate",
      "compositionupdate focusout keydown keypress keyup mousedown".split(" "),
    ));
  var ru =
      "abort canplay canplaythrough durationchange emptied encrypted ended error loadeddata loadedmetadata loadstart pause play playing progress ratechange resize seeked seeking stalled suspend timeupdate volumechange waiting".split(
        " ",
      ),
    Dh = new Set(
      "beforetoggle cancel close invalid load scroll scrollend toggle".split(" ").concat(ru),
    );
  function Q0(l, t) {
    t = (t & 4) !== 0;
    for (var a = 0; a < l.length; a++) {
      var e = l[a],
        u = e.event;
      e = e.listeners;
      l: {
        var n = void 0;
        if (t)
          for (var i = e.length - 1; 0 <= i; i--) {
            var c = e[i],
              f = c.instance,
              y = c.currentTarget;
            if (((c = c.listener), f !== n && u.isPropagationStopped())) break l;
            ((n = c), (u.currentTarget = y));
            try {
              n(u);
            } catch (g) {
              Vu(g);
            }
            ((u.currentTarget = null), (n = f));
          }
        else
          for (i = 0; i < e.length; i++) {
            if (
              ((c = e[i]),
              (f = c.instance),
              (y = c.currentTarget),
              (c = c.listener),
              f !== n && u.isPropagationStopped())
            )
              break l;
            ((n = c), (u.currentTarget = y));
            try {
              n(u);
            } catch (g) {
              Vu(g);
            }
            ((u.currentTarget = null), (n = f));
          }
      }
    }
  }
  function J(l, t) {
    var a = t[ai];
    a === void 0 && (a = t[ai] = new Set());
    var e = l + "__bubble";
    a.has(e) || (Z0(t, l, 2, !1), a.add(e));
  }
  function Lc(l, t, a) {
    var e = 0;
    (t && (e |= 4), Z0(a, l, e, t));
  }
  var Un = "_reactListening" + Math.random().toString(36).slice(2);
  function Kc(l) {
    if (!l[Un]) {
      ((l[Un] = !0),
        xf.forEach(function (a) {
          a !== "selectionchange" && (Dh.has(a) || Lc(a, !1, l), Lc(a, !0, l));
        }));
      var t = l.nodeType === 9 ? l : l.ownerDocument;
      t === null || t[Un] || ((t[Un] = !0), Lc("selectionchange", !1, t));
    }
  }
  function Z0(l, t, a, e) {
    switch (gm(t)) {
      case 2:
        var u = ey;
        break;
      case 8:
        u = uy;
        break;
      default:
        u = cf;
    }
    ((a = u.bind(null, t, a, l)),
      (u = void 0),
      !mi || (t !== "touchstart" && t !== "touchmove" && t !== "wheel") || (u = !0),
      e
        ? u !== void 0
          ? l.addEventListener(t, a, { capture: !0, passive: u })
          : l.addEventListener(t, a, !0)
        : u !== void 0
          ? l.addEventListener(t, a, { passive: u })
          : l.addEventListener(t, a, !1));
  }
  function Jc(l, t, a, e, u) {
    var n = e;
    if ((t & 1) === 0 && (t & 2) === 0 && e !== null)
      l: for (;;) {
        if (e === null) return;
        var i = e.tag;
        if (i === 3 || i === 4) {
          var c = e.stateNode.containerInfo;
          if (c === u) break;
          if (i === 4)
            for (i = e.return; i !== null;) {
              var f = i.tag;
              if ((f === 3 || f === 4) && i.stateNode.containerInfo === u) return;
              i = i.return;
            }
          for (; c !== null;) {
            if (((i = $a(c)), i === null)) return;
            if (((f = i.tag), f === 5 || f === 6 || f === 26 || f === 27)) {
              e = n = i;
              continue l;
            }
            c = c.parentNode;
          }
        }
        e = e.return;
      }
    Jf(function () {
      var y = n,
        g = si(a),
        _ = [];
      l: {
        var v = zs.get(l);
        if (v !== void 0) {
          var r = Xu,
            M = l;
          switch (l) {
            case "keypress":
              if (Yu(a) === 0) break l;
            case "keydown":
            case "keyup":
              r = Td;
              break;
            case "focusin":
              ((M = "focus"), (r = vi));
              break;
            case "focusout":
              ((M = "blur"), (r = vi));
              break;
            case "beforeblur":
            case "afterblur":
              r = vi;
              break;
            case "click":
              if (a.button === 2) break l;
            case "auxclick":
            case "dblclick":
            case "mousedown":
            case "mousemove":
            case "mouseup":
            case "mouseout":
            case "mouseover":
            case "contextmenu":
              r = $f;
              break;
            case "drag":
            case "dragend":
            case "dragenter":
            case "dragexit":
            case "dragleave":
            case "dragover":
            case "dragstart":
            case "drop":
              r = od;
              break;
            case "touchcancel":
            case "touchend":
            case "touchmove":
            case "touchstart":
              r = pd;
              break;
            case rs:
            case gs:
            case Ss:
              r = hd;
              break;
            case bs:
              r = Md;
              break;
            case "scroll":
            case "scrollend":
              r = fd;
              break;
            case "wheel":
              r = Dd;
              break;
            case "copy":
            case "cut":
            case "paste":
              r = vd;
              break;
            case "gotpointercapture":
            case "lostpointercapture":
            case "pointercancel":
            case "pointerdown":
            case "pointermove":
            case "pointerout":
            case "pointerover":
            case "pointerup":
              r = Ff;
              break;
            case "toggle":
            case "beforetoggle":
              r = Hd;
          }
          var C = (t & 4) !== 0,
            cl = !C && (l === "scroll" || l === "scrollend"),
            m = C ? (v !== null ? v + "Capture" : null) : v;
          C = [];
          for (var s = y, h; s !== null;) {
            var z = s;
            if (
              ((h = z.stateNode),
              (z = z.tag),
              (z !== 5 && z !== 26 && z !== 27) ||
                h === null ||
                m === null ||
                ((z = Ye(s, m)), z != null && C.push(gu(s, z, h))),
              cl)
            )
              break;
            s = s.return;
          }
          0 < C.length && ((v = new r(v, M, null, a, g)), _.push({ event: v, listeners: C }));
        }
      }
      if ((t & 7) === 0) {
        l: {
          if (
            ((v = l === "mouseover" || l === "pointerover"),
            (r = l === "mouseout" || l === "pointerout"),
            v && a !== fi && (M = a.relatedTarget || a.fromElement) && ($a(M) || M[Wa]))
          )
            break l;
          if (
            (r || v) &&
            ((v =
              g.window === g
                ? g
                : (v = g.ownerDocument)
                  ? v.defaultView || v.parentWindow
                  : window),
            r
              ? ((M = a.relatedTarget || a.toElement),
                (r = y),
                (M = M ? $a(M) : null),
                M !== null &&
                  ((cl = V(M)), (C = M.tag), M !== cl || (C !== 5 && C !== 27 && C !== 6)) &&
                  (M = null))
              : ((r = null), (M = y)),
            r !== M)
          ) {
            if (
              ((C = $f),
              (z = "onMouseLeave"),
              (m = "onMouseEnter"),
              (s = "mouse"),
              (l === "pointerout" || l === "pointerover") &&
                ((C = Ff), (z = "onPointerLeave"), (m = "onPointerEnter"), (s = "pointer")),
              (cl = r == null ? v : Be(r)),
              (h = M == null ? v : Be(M)),
              (v = new C(z, s + "leave", r, a, g)),
              (v.target = cl),
              (v.relatedTarget = h),
              (z = null),
              $a(g) === y &&
                ((C = new C(m, s + "enter", M, a, g)),
                (C.target = h),
                (C.relatedTarget = cl),
                (z = C)),
              (cl = z),
              r && M)
            )
              t: {
                for (C = Uh, m = r, s = M, h = 0, z = m; z; z = C(z)) h++;
                z = 0;
                for (var x = s; x; x = C(x)) z++;
                for (; 0 < h - z;) ((m = C(m)), h--);
                for (; 0 < z - h;) ((s = C(s)), z--);
                for (; h--;) {
                  if (m === s || (s !== null && m === s.alternate)) {
                    C = m;
                    break t;
                  }
                  ((m = C(m)), (s = C(s)));
                }
                C = null;
              }
            else C = null;
            (r !== null && V0(_, v, r, C, !1), M !== null && cl !== null && V0(_, cl, M, C, !0));
          }
        }
        l: {
          if (
            ((v = y ? Be(y) : window),
            (r = v.nodeName && v.nodeName.toLowerCase()),
            r === "select" || (r === "input" && v.type === "file"))
          )
            var F = ns;
          else if (es(v))
            if (is) F = Qd;
            else {
              F = Gd;
              var H = Yd;
            }
          else
            ((r = v.nodeName),
              !r || r.toLowerCase() !== "input" || (v.type !== "checkbox" && v.type !== "radio")
                ? y && ci(y.elementType) && (F = ns)
                : (F = Xd));
          if (F && (F = F(l, y))) {
            us(_, F, a, g);
            break l;
          }
          (H && H(l, v, y),
            l === "focusout" &&
              y &&
              v.type === "number" &&
              y.memoizedProps.value != null &&
              ii(v, "number", v.value));
        }
        switch (((H = y ? Be(y) : window), l)) {
          case "focusin":
            (es(H) || H.contentEditable === "true") && ((ue = H), (_i = y), (Je = null));
            break;
          case "focusout":
            Je = _i = ue = null;
            break;
          case "mousedown":
            Ti = !0;
            break;
          case "contextmenu":
          case "mouseup":
          case "dragend":
            ((Ti = !1), ys(_, a, g));
            break;
          case "selectionchange":
            if (Vd) break;
          case "keydown":
          case "keyup":
            ys(_, a, g);
        }
        var Z;
        if (gi)
          l: {
            switch (l) {
              case "compositionstart":
                var W = "onCompositionStart";
                break l;
              case "compositionend":
                W = "onCompositionEnd";
                break l;
              case "compositionupdate":
                W = "onCompositionUpdate";
                break l;
            }
            W = void 0;
          }
        else
          ee
            ? ts(l, a) && (W = "onCompositionEnd")
            : l === "keydown" && a.keyCode === 229 && (W = "onCompositionStart");
        (W &&
          (If &&
            a.locale !== "ko" &&
            (ee || W !== "onCompositionStart"
              ? W === "onCompositionEnd" && ee && (Z = wf())
              : ((la = g), (di = "value" in la ? la.value : la.textContent), (ee = !0))),
          (H = Hn(y, W)),
          0 < H.length &&
            ((W = new kf(W, l, null, a, g)),
            _.push({ event: W, listeners: H }),
            Z ? (W.data = Z) : ((Z = as(a)), Z !== null && (W.data = Z)))),
          (Z = Rd ? xd(l, a) : Cd(l, a)) &&
            ((W = Hn(y, "onBeforeInput")),
            0 < W.length &&
              ((H = new kf("onBeforeInput", "beforeinput", null, a, g)),
              _.push({ event: H, listeners: W }),
              (H.data = Z))),
          Oh(_, l, y, a, g));
      }
      Q0(_, t);
    });
  }
  function gu(l, t, a) {
    return { instance: l, listener: t, currentTarget: a };
  }
  function Hn(l, t) {
    for (var a = t + "Capture", e = []; l !== null;) {
      var u = l,
        n = u.stateNode;
      if (
        ((u = u.tag),
        (u !== 5 && u !== 26 && u !== 27) ||
          n === null ||
          ((u = Ye(l, a)),
          u != null && e.unshift(gu(l, u, n)),
          (u = Ye(l, t)),
          u != null && e.push(gu(l, u, n))),
        l.tag === 3)
      )
        return e;
      l = l.return;
    }
    return [];
  }
  function Uh(l) {
    if (l === null) return null;
    do l = l.return;
    while (l && l.tag !== 5 && l.tag !== 27);
    return l || null;
  }
  function V0(l, t, a, e, u) {
    for (var n = t._reactName, i = []; a !== null && a !== e;) {
      var c = a,
        f = c.alternate,
        y = c.stateNode;
      if (((c = c.tag), f !== null && f === e)) break;
      ((c !== 5 && c !== 26 && c !== 27) ||
        y === null ||
        ((f = y),
        u
          ? ((y = Ye(a, n)), y != null && i.unshift(gu(a, y, f)))
          : u || ((y = Ye(a, n)), y != null && i.push(gu(a, y, f)))),
        (a = a.return));
    }
    i.length !== 0 && l.push({ event: t, listeners: i });
  }
  var Hh = /\r\n?/g,
    jh = /\u0000|\uFFFD/g;
  function L0(l) {
    return (typeof l == "string" ? l : "" + l)
      .replace(
        Hh,
        `
`,
      )
      .replace(jh, "");
  }
  function K0(l, t) {
    return ((t = L0(t)), L0(l) === t);
  }
  function il(l, t, a, e, u, n) {
    switch (a) {
      case "children":
        typeof e == "string"
          ? t === "body" || (t === "textarea" && e === "") || le(l, e)
          : (typeof e == "number" || typeof e == "bigint") && t !== "body" && le(l, "" + e);
        break;
      case "className":
        xu(l, "class", e);
        break;
      case "tabIndex":
        xu(l, "tabindex", e);
        break;
      case "dir":
      case "role":
      case "viewBox":
      case "width":
      case "height":
        xu(l, a, e);
        break;
      case "style":
        Lf(l, e, n);
        break;
      case "data":
        if (t !== "object") {
          xu(l, "data", e);
          break;
        }
      case "src":
      case "href":
        if (e === "" && (t !== "a" || a !== "href")) {
          l.removeAttribute(a);
          break;
        }
        if (e == null || typeof e == "function" || typeof e == "symbol" || typeof e == "boolean") {
          l.removeAttribute(a);
          break;
        }
        ((e = qu("" + e)), l.setAttribute(a, e));
        break;
      case "action":
      case "formAction":
        if (typeof e == "function") {
          l.setAttribute(
            a,
            "javascript:throw new Error('A React form was unexpectedly submitted. If you called form.submit() manually, consider using form.requestSubmit() instead. If you\\'re trying to use event.stopPropagation() in a submit event handler, consider also calling event.preventDefault().')",
          );
          break;
        } else
          typeof n == "function" &&
            (a === "formAction"
              ? (t !== "input" && il(l, t, "name", u.name, u, null),
                il(l, t, "formEncType", u.formEncType, u, null),
                il(l, t, "formMethod", u.formMethod, u, null),
                il(l, t, "formTarget", u.formTarget, u, null))
              : (il(l, t, "encType", u.encType, u, null),
                il(l, t, "method", u.method, u, null),
                il(l, t, "target", u.target, u, null)));
        if (e == null || typeof e == "symbol" || typeof e == "boolean") {
          l.removeAttribute(a);
          break;
        }
        ((e = qu("" + e)), l.setAttribute(a, e));
        break;
      case "onClick":
        e != null && (l.onclick = Rt);
        break;
      case "onScroll":
        e != null && J("scroll", l);
        break;
      case "onScrollEnd":
        e != null && J("scrollend", l);
        break;
      case "dangerouslySetInnerHTML":
        if (e != null) {
          if (typeof e != "object" || !("__html" in e)) throw Error(d(61));
          if (((a = e.__html), a != null)) {
            if (u.children != null) throw Error(d(60));
            l.innerHTML = a;
          }
        }
        break;
      case "multiple":
        l.multiple = e && typeof e != "function" && typeof e != "symbol";
        break;
      case "muted":
        l.muted = e && typeof e != "function" && typeof e != "symbol";
        break;
      case "suppressContentEditableWarning":
      case "suppressHydrationWarning":
      case "defaultValue":
      case "defaultChecked":
      case "innerHTML":
      case "ref":
        break;
      case "autoFocus":
        break;
      case "xlinkHref":
        if (e == null || typeof e == "function" || typeof e == "boolean" || typeof e == "symbol") {
          l.removeAttribute("xlink:href");
          break;
        }
        ((a = qu("" + e)), l.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", a));
        break;
      case "contentEditable":
      case "spellCheck":
      case "draggable":
      case "value":
      case "autoReverse":
      case "externalResourcesRequired":
      case "focusable":
      case "preserveAlpha":
        e != null && typeof e != "function" && typeof e != "symbol"
          ? l.setAttribute(a, "" + e)
          : l.removeAttribute(a);
        break;
      case "inert":
      case "allowFullScreen":
      case "async":
      case "autoPlay":
      case "controls":
      case "default":
      case "defer":
      case "disabled":
      case "disablePictureInPicture":
      case "disableRemotePlayback":
      case "formNoValidate":
      case "hidden":
      case "loop":
      case "noModule":
      case "noValidate":
      case "open":
      case "playsInline":
      case "readOnly":
      case "required":
      case "reversed":
      case "scoped":
      case "seamless":
      case "itemScope":
        e && typeof e != "function" && typeof e != "symbol"
          ? l.setAttribute(a, "")
          : l.removeAttribute(a);
        break;
      case "capture":
      case "download":
        e === !0
          ? l.setAttribute(a, "")
          : e !== !1 && e != null && typeof e != "function" && typeof e != "symbol"
            ? l.setAttribute(a, e)
            : l.removeAttribute(a);
        break;
      case "cols":
      case "rows":
      case "size":
      case "span":
        e != null && typeof e != "function" && typeof e != "symbol" && !isNaN(e) && 1 <= e
          ? l.setAttribute(a, e)
          : l.removeAttribute(a);
        break;
      case "rowSpan":
      case "start":
        e == null || typeof e == "function" || typeof e == "symbol" || isNaN(e)
          ? l.removeAttribute(a)
          : l.setAttribute(a, e);
        break;
      case "popover":
        (J("beforetoggle", l), J("toggle", l), Ru(l, "popover", e));
        break;
      case "xlinkActuate":
        jt(l, "http://www.w3.org/1999/xlink", "xlink:actuate", e);
        break;
      case "xlinkArcrole":
        jt(l, "http://www.w3.org/1999/xlink", "xlink:arcrole", e);
        break;
      case "xlinkRole":
        jt(l, "http://www.w3.org/1999/xlink", "xlink:role", e);
        break;
      case "xlinkShow":
        jt(l, "http://www.w3.org/1999/xlink", "xlink:show", e);
        break;
      case "xlinkTitle":
        jt(l, "http://www.w3.org/1999/xlink", "xlink:title", e);
        break;
      case "xlinkType":
        jt(l, "http://www.w3.org/1999/xlink", "xlink:type", e);
        break;
      case "xmlBase":
        jt(l, "http://www.w3.org/XML/1998/namespace", "xml:base", e);
        break;
      case "xmlLang":
        jt(l, "http://www.w3.org/XML/1998/namespace", "xml:lang", e);
        break;
      case "xmlSpace":
        jt(l, "http://www.w3.org/XML/1998/namespace", "xml:space", e);
        break;
      case "is":
        Ru(l, "is", e);
        break;
      case "innerText":
      case "textContent":
        break;
      default:
        (!(2 < a.length) || (a[0] !== "o" && a[0] !== "O") || (a[1] !== "n" && a[1] !== "N")) &&
          ((a = id.get(a) || a), Ru(l, a, e));
    }
  }
  function wc(l, t, a, e, u, n) {
    switch (a) {
      case "style":
        Lf(l, e, n);
        break;
      case "dangerouslySetInnerHTML":
        if (e != null) {
          if (typeof e != "object" || !("__html" in e)) throw Error(d(61));
          if (((a = e.__html), a != null)) {
            if (u.children != null) throw Error(d(60));
            l.innerHTML = a;
          }
        }
        break;
      case "children":
        typeof e == "string"
          ? le(l, e)
          : (typeof e == "number" || typeof e == "bigint") && le(l, "" + e);
        break;
      case "onScroll":
        e != null && J("scroll", l);
        break;
      case "onScrollEnd":
        e != null && J("scrollend", l);
        break;
      case "onClick":
        e != null && (l.onclick = Rt);
        break;
      case "suppressContentEditableWarning":
      case "suppressHydrationWarning":
      case "innerHTML":
      case "ref":
        break;
      case "innerText":
      case "textContent":
        break;
      default:
        if (!Cf.hasOwnProperty(a))
          l: {
            if (
              a[0] === "o" &&
              a[1] === "n" &&
              ((u = a.endsWith("Capture")),
              (t = a.slice(2, u ? a.length - 7 : void 0)),
              (n = l[Vl] || null),
              (n = n != null ? n[a] : null),
              typeof n == "function" && l.removeEventListener(t, n, u),
              typeof e == "function")
            ) {
              (typeof n != "function" &&
                n !== null &&
                (a in l ? (l[a] = null) : l.hasAttribute(a) && l.removeAttribute(a)),
                l.addEventListener(t, e, u));
              break l;
            }
            a in l ? (l[a] = e) : e === !0 ? l.setAttribute(a, "") : Ru(l, a, e);
          }
    }
  }
  function Rl(l, t, a) {
    switch (t) {
      case "div":
      case "span":
      case "svg":
      case "path":
      case "a":
      case "g":
      case "p":
      case "li":
        break;
      case "img":
        (J("error", l), J("load", l));
        var e = !1,
          u = !1,
          n;
        for (n in a)
          if (a.hasOwnProperty(n)) {
            var i = a[n];
            if (i != null)
              switch (n) {
                case "src":
                  e = !0;
                  break;
                case "srcSet":
                  u = !0;
                  break;
                case "children":
                case "dangerouslySetInnerHTML":
                  throw Error(d(137, t));
                default:
                  il(l, t, n, i, a, null);
              }
          }
        (u && il(l, t, "srcSet", a.srcSet, a, null), e && il(l, t, "src", a.src, a, null));
        return;
      case "input":
        J("invalid", l);
        var c = (n = i = u = null),
          f = null,
          y = null;
        for (e in a)
          if (a.hasOwnProperty(e)) {
            var g = a[e];
            if (g != null)
              switch (e) {
                case "name":
                  u = g;
                  break;
                case "type":
                  i = g;
                  break;
                case "checked":
                  f = g;
                  break;
                case "defaultChecked":
                  y = g;
                  break;
                case "value":
                  n = g;
                  break;
                case "defaultValue":
                  c = g;
                  break;
                case "children":
                case "dangerouslySetInnerHTML":
                  if (g != null) throw Error(d(137, t));
                  break;
                default:
                  il(l, t, e, g, a, null);
              }
          }
        Xf(l, n, c, f, y, i, u, !1);
        return;
      case "select":
        (J("invalid", l), (e = i = n = null));
        for (u in a)
          if (a.hasOwnProperty(u) && ((c = a[u]), c != null))
            switch (u) {
              case "value":
                n = c;
                break;
              case "defaultValue":
                i = c;
                break;
              case "multiple":
                e = c;
              default:
                il(l, t, u, c, a, null);
            }
        ((t = n),
          (a = i),
          (l.multiple = !!e),
          t != null ? Pa(l, !!e, t, !1) : a != null && Pa(l, !!e, a, !0));
        return;
      case "textarea":
        (J("invalid", l), (n = u = e = null));
        for (i in a)
          if (a.hasOwnProperty(i) && ((c = a[i]), c != null))
            switch (i) {
              case "value":
                e = c;
                break;
              case "defaultValue":
                u = c;
                break;
              case "children":
                n = c;
                break;
              case "dangerouslySetInnerHTML":
                if (c != null) throw Error(d(91));
                break;
              default:
                il(l, t, i, c, a, null);
            }
        Zf(l, e, u, n);
        return;
      case "option":
        for (f in a)
          a.hasOwnProperty(f) &&
            ((e = a[f]), e != null) &&
            (f === "selected"
              ? (l.selected = e && typeof e != "function" && typeof e != "symbol")
              : il(l, t, f, e, a, null));
        return;
      case "dialog":
        (J("beforetoggle", l), J("toggle", l), J("cancel", l), J("close", l));
        break;
      case "iframe":
      case "object":
        J("load", l);
        break;
      case "video":
      case "audio":
        for (e = 0; e < ru.length; e++) J(ru[e], l);
        break;
      case "image":
        (J("error", l), J("load", l));
        break;
      case "details":
        J("toggle", l);
        break;
      case "embed":
      case "source":
      case "link":
        (J("error", l), J("load", l));
      case "area":
      case "base":
      case "br":
      case "col":
      case "hr":
      case "keygen":
      case "meta":
      case "param":
      case "track":
      case "wbr":
      case "menuitem":
        for (y in a)
          if (a.hasOwnProperty(y) && ((e = a[y]), e != null))
            switch (y) {
              case "children":
              case "dangerouslySetInnerHTML":
                throw Error(d(137, t));
              default:
                il(l, t, y, e, a, null);
            }
        return;
      default:
        if (ci(t)) {
          for (g in a)
            a.hasOwnProperty(g) && ((e = a[g]), e !== void 0 && wc(l, t, g, e, a, void 0));
          return;
        }
    }
    for (c in a) a.hasOwnProperty(c) && ((e = a[c]), e != null && il(l, t, c, e, a, null));
  }
  function Rh(l, t, a, e) {
    switch (t) {
      case "div":
      case "span":
      case "svg":
      case "path":
      case "a":
      case "g":
      case "p":
      case "li":
        break;
      case "input":
        var u = null,
          n = null,
          i = null,
          c = null,
          f = null,
          y = null,
          g = null;
        for (r in a) {
          var _ = a[r];
          if (a.hasOwnProperty(r) && _ != null)
            switch (r) {
              case "checked":
                break;
              case "value":
                break;
              case "defaultValue":
                f = _;
              default:
                e.hasOwnProperty(r) || il(l, t, r, null, e, _);
            }
        }
        for (var v in e) {
          var r = e[v];
          if (((_ = a[v]), e.hasOwnProperty(v) && (r != null || _ != null)))
            switch (v) {
              case "type":
                n = r;
                break;
              case "name":
                u = r;
                break;
              case "checked":
                y = r;
                break;
              case "defaultChecked":
                g = r;
                break;
              case "value":
                i = r;
                break;
              case "defaultValue":
                c = r;
                break;
              case "children":
              case "dangerouslySetInnerHTML":
                if (r != null) throw Error(d(137, t));
                break;
              default:
                r !== _ && il(l, t, v, r, e, _);
            }
        }
        ni(l, i, c, f, y, g, n, u);
        return;
      case "select":
        r = i = c = v = null;
        for (n in a)
          if (((f = a[n]), a.hasOwnProperty(n) && f != null))
            switch (n) {
              case "value":
                break;
              case "multiple":
                r = f;
              default:
                e.hasOwnProperty(n) || il(l, t, n, null, e, f);
            }
        for (u in e)
          if (((n = e[u]), (f = a[u]), e.hasOwnProperty(u) && (n != null || f != null)))
            switch (u) {
              case "value":
                v = n;
                break;
              case "defaultValue":
                c = n;
                break;
              case "multiple":
                i = n;
              default:
                n !== f && il(l, t, u, n, e, f);
            }
        ((t = c),
          (a = i),
          (e = r),
          v != null
            ? Pa(l, !!a, v, !1)
            : !!e != !!a && (t != null ? Pa(l, !!a, t, !0) : Pa(l, !!a, a ? [] : "", !1)));
        return;
      case "textarea":
        r = v = null;
        for (c in a)
          if (((u = a[c]), a.hasOwnProperty(c) && u != null && !e.hasOwnProperty(c)))
            switch (c) {
              case "value":
                break;
              case "children":
                break;
              default:
                il(l, t, c, null, e, u);
            }
        for (i in e)
          if (((u = e[i]), (n = a[i]), e.hasOwnProperty(i) && (u != null || n != null)))
            switch (i) {
              case "value":
                v = u;
                break;
              case "defaultValue":
                r = u;
                break;
              case "children":
                break;
              case "dangerouslySetInnerHTML":
                if (u != null) throw Error(d(91));
                break;
              default:
                u !== n && il(l, t, i, u, e, n);
            }
        Qf(l, v, r);
        return;
      case "option":
        for (var M in a)
          ((v = a[M]),
            a.hasOwnProperty(M) &&
              v != null &&
              !e.hasOwnProperty(M) &&
              (M === "selected" ? (l.selected = !1) : il(l, t, M, null, e, v)));
        for (f in e)
          ((v = e[f]),
            (r = a[f]),
            e.hasOwnProperty(f) &&
              v !== r &&
              (v != null || r != null) &&
              (f === "selected"
                ? (l.selected = v && typeof v != "function" && typeof v != "symbol")
                : il(l, t, f, v, e, r)));
        return;
      case "img":
      case "link":
      case "area":
      case "base":
      case "br":
      case "col":
      case "embed":
      case "hr":
      case "keygen":
      case "meta":
      case "param":
      case "source":
      case "track":
      case "wbr":
      case "menuitem":
        for (var C in a)
          ((v = a[C]),
            a.hasOwnProperty(C) && v != null && !e.hasOwnProperty(C) && il(l, t, C, null, e, v));
        for (y in e)
          if (((v = e[y]), (r = a[y]), e.hasOwnProperty(y) && v !== r && (v != null || r != null)))
            switch (y) {
              case "children":
              case "dangerouslySetInnerHTML":
                if (v != null) throw Error(d(137, t));
                break;
              default:
                il(l, t, y, v, e, r);
            }
        return;
      default:
        if (ci(t)) {
          for (var cl in a)
            ((v = a[cl]),
              a.hasOwnProperty(cl) &&
                v !== void 0 &&
                !e.hasOwnProperty(cl) &&
                wc(l, t, cl, void 0, e, v));
          for (g in e)
            ((v = e[g]),
              (r = a[g]),
              !e.hasOwnProperty(g) ||
                v === r ||
                (v === void 0 && r === void 0) ||
                wc(l, t, g, v, e, r));
          return;
        }
    }
    for (var m in a)
      ((v = a[m]),
        a.hasOwnProperty(m) && v != null && !e.hasOwnProperty(m) && il(l, t, m, null, e, v));
    for (_ in e)
      ((v = e[_]),
        (r = a[_]),
        !e.hasOwnProperty(_) || v === r || (v == null && r == null) || il(l, t, _, v, e, r));
  }
  function J0(l) {
    switch (l) {
      case "css":
      case "script":
      case "font":
      case "img":
      case "image":
      case "input":
      case "link":
        return !0;
      default:
        return !1;
    }
  }
  function xh() {
    if (typeof performance.getEntriesByType == "function") {
      for (
        var l = 0, t = 0, a = performance.getEntriesByType("resource"), e = 0;
        e < a.length;
        e++
      ) {
        var u = a[e],
          n = u.transferSize,
          i = u.initiatorType,
          c = u.duration;
        if (n && c && J0(i)) {
          for (i = 0, c = u.responseEnd, e += 1; e < a.length; e++) {
            var f = a[e],
              y = f.startTime;
            if (y > c) break;
            var g = f.transferSize,
              _ = f.initiatorType;
            g && J0(_) && ((f = f.responseEnd), (i += g * (f < c ? 1 : (c - y) / (f - y))));
          }
          if ((--e, (t += (8 * (n + i)) / (u.duration / 1e3)), l++, 10 < l)) break;
        }
      }
      if (0 < l) return t / l / 1e6;
    }
    return navigator.connection && ((l = navigator.connection.downlink), typeof l == "number")
      ? l
      : 5;
  }
  var Wc = null,
    $c = null;
  function jn(l) {
    return l.nodeType === 9 ? l : l.ownerDocument;
  }
  function w0(l) {
    switch (l) {
      case "http://www.w3.org/2000/svg":
        return 1;
      case "http://www.w3.org/1998/Math/MathML":
        return 2;
      default:
        return 0;
    }
  }
  function W0(l, t) {
    if (l === 0)
      switch (t) {
        case "svg":
          return 1;
        case "math":
          return 2;
        default:
          return 0;
      }
    return l === 1 && t === "foreignObject" ? 0 : l;
  }
  function kc(l, t) {
    return (
      l === "textarea" ||
      l === "noscript" ||
      typeof t.children == "string" ||
      typeof t.children == "number" ||
      typeof t.children == "bigint" ||
      (typeof t.dangerouslySetInnerHTML == "object" &&
        t.dangerouslySetInnerHTML !== null &&
        t.dangerouslySetInnerHTML.__html != null)
    );
  }
  var Fc = null;
  function Ch() {
    var l = window.event;
    return l && l.type === "popstate" ? (l === Fc ? !1 : ((Fc = l), !0)) : ((Fc = null), !1);
  }
  var $0 = typeof setTimeout == "function" ? setTimeout : void 0,
    qh = typeof clearTimeout == "function" ? clearTimeout : void 0,
    k0 = typeof Promise == "function" ? Promise : void 0,
    Bh =
      typeof queueMicrotask == "function"
        ? queueMicrotask
        : typeof k0 < "u"
          ? function (l) {
              return k0.resolve(null).then(l).catch(Yh);
            }
          : $0;
  function Yh(l) {
    setTimeout(function () {
      throw l;
    });
  }
  function ga(l) {
    return l === "head";
  }
  function F0(l, t) {
    var a = t,
      e = 0;
    do {
      var u = a.nextSibling;
      if ((l.removeChild(a), u && u.nodeType === 8))
        if (((a = u.data), a === "/$" || a === "/&")) {
          if (e === 0) {
            (l.removeChild(u), He(t));
            return;
          }
          e--;
        } else if (a === "$" || a === "$?" || a === "$~" || a === "$!" || a === "&") e++;
        else if (a === "html") Su(l.ownerDocument.documentElement);
        else if (a === "head") {
          ((a = l.ownerDocument.head), Su(a));
          for (var n = a.firstChild; n;) {
            var i = n.nextSibling,
              c = n.nodeName;
            (n[qe] ||
              c === "SCRIPT" ||
              c === "STYLE" ||
              (c === "LINK" && n.rel.toLowerCase() === "stylesheet") ||
              a.removeChild(n),
              (n = i));
          }
        } else a === "body" && Su(l.ownerDocument.body);
      a = u;
    } while (a);
    He(t);
  }
  function I0(l, t) {
    var a = l;
    l = 0;
    do {
      var e = a.nextSibling;
      if (
        (a.nodeType === 1
          ? t
            ? ((a._stashedDisplay = a.style.display), (a.style.display = "none"))
            : ((a.style.display = a._stashedDisplay || ""),
              a.getAttribute("style") === "" && a.removeAttribute("style"))
          : a.nodeType === 3 &&
            (t
              ? ((a._stashedText = a.nodeValue), (a.nodeValue = ""))
              : (a.nodeValue = a._stashedText || "")),
        e && e.nodeType === 8)
      )
        if (((a = e.data), a === "/$")) {
          if (l === 0) break;
          l--;
        } else (a !== "$" && a !== "$?" && a !== "$~" && a !== "$!") || l++;
      a = e;
    } while (a);
  }
  function Ic(l) {
    var t = l.firstChild;
    for (t && t.nodeType === 10 && (t = t.nextSibling); t;) {
      var a = t;
      switch (((t = t.nextSibling), a.nodeName)) {
        case "HTML":
        case "HEAD":
        case "BODY":
          (Ic(a), ei(a));
          continue;
        case "SCRIPT":
        case "STYLE":
          continue;
        case "LINK":
          if (a.rel.toLowerCase() === "stylesheet") continue;
      }
      l.removeChild(a);
    }
  }
  function Gh(l, t, a, e) {
    for (; l.nodeType === 1;) {
      var u = a;
      if (l.nodeName.toLowerCase() !== t.toLowerCase()) {
        if (!e && (l.nodeName !== "INPUT" || l.type !== "hidden")) break;
      } else if (e) {
        if (!l[qe])
          switch (t) {
            case "meta":
              if (!l.hasAttribute("itemprop")) break;
              return l;
            case "link":
              if (
                ((n = l.getAttribute("rel")),
                n === "stylesheet" && l.hasAttribute("data-precedence"))
              )
                break;
              if (
                n !== u.rel ||
                l.getAttribute("href") !== (u.href == null || u.href === "" ? null : u.href) ||
                l.getAttribute("crossorigin") !== (u.crossOrigin == null ? null : u.crossOrigin) ||
                l.getAttribute("title") !== (u.title == null ? null : u.title)
              )
                break;
              return l;
            case "style":
              if (l.hasAttribute("data-precedence")) break;
              return l;
            case "script":
              if (
                ((n = l.getAttribute("src")),
                (n !== (u.src == null ? null : u.src) ||
                  l.getAttribute("type") !== (u.type == null ? null : u.type) ||
                  l.getAttribute("crossorigin") !==
                    (u.crossOrigin == null ? null : u.crossOrigin)) &&
                  n &&
                  l.hasAttribute("async") &&
                  !l.hasAttribute("itemprop"))
              )
                break;
              return l;
            default:
              return l;
          }
      } else if (t === "input" && l.type === "hidden") {
        var n = u.name == null ? null : "" + u.name;
        if (u.type === "hidden" && l.getAttribute("name") === n) return l;
      } else return l;
      if (((l = gt(l.nextSibling)), l === null)) break;
    }
    return null;
  }
  function Xh(l, t, a) {
    if (t === "") return null;
    for (; l.nodeType !== 3;)
      if (
        ((l.nodeType !== 1 || l.nodeName !== "INPUT" || l.type !== "hidden") && !a) ||
        ((l = gt(l.nextSibling)), l === null)
      )
        return null;
    return l;
  }
  function P0(l, t) {
    for (; l.nodeType !== 8;)
      if (
        ((l.nodeType !== 1 || l.nodeName !== "INPUT" || l.type !== "hidden") && !t) ||
        ((l = gt(l.nextSibling)), l === null)
      )
        return null;
    return l;
  }
  function Pc(l) {
    return l.data === "$?" || l.data === "$~";
  }
  function lf(l) {
    return l.data === "$!" || (l.data === "$?" && l.ownerDocument.readyState !== "loading");
  }
  function Qh(l, t) {
    var a = l.ownerDocument;
    if (l.data === "$~") l._reactRetry = t;
    else if (l.data !== "$?" || a.readyState !== "loading") t();
    else {
      var e = function () {
        (t(), a.removeEventListener("DOMContentLoaded", e));
      };
      (a.addEventListener("DOMContentLoaded", e), (l._reactRetry = e));
    }
  }
  function gt(l) {
    for (; l != null; l = l.nextSibling) {
      var t = l.nodeType;
      if (t === 1 || t === 3) break;
      if (t === 8) {
        if (
          ((t = l.data),
          t === "$" ||
            t === "$!" ||
            t === "$?" ||
            t === "$~" ||
            t === "&" ||
            t === "F!" ||
            t === "F")
        )
          break;
        if (t === "/$" || t === "/&") return null;
      }
    }
    return l;
  }
  var tf = null;
  function lm(l) {
    l = l.nextSibling;
    for (var t = 0; l;) {
      if (l.nodeType === 8) {
        var a = l.data;
        if (a === "/$" || a === "/&") {
          if (t === 0) return gt(l.nextSibling);
          t--;
        } else (a !== "$" && a !== "$!" && a !== "$?" && a !== "$~" && a !== "&") || t++;
      }
      l = l.nextSibling;
    }
    return null;
  }
  function tm(l) {
    l = l.previousSibling;
    for (var t = 0; l;) {
      if (l.nodeType === 8) {
        var a = l.data;
        if (a === "$" || a === "$!" || a === "$?" || a === "$~" || a === "&") {
          if (t === 0) return l;
          t--;
        } else (a !== "/$" && a !== "/&") || t++;
      }
      l = l.previousSibling;
    }
    return null;
  }
  function am(l, t, a) {
    switch (((t = jn(a)), l)) {
      case "html":
        if (((l = t.documentElement), !l)) throw Error(d(452));
        return l;
      case "head":
        if (((l = t.head), !l)) throw Error(d(453));
        return l;
      case "body":
        if (((l = t.body), !l)) throw Error(d(454));
        return l;
      default:
        throw Error(d(451));
    }
  }
  function Su(l) {
    for (var t = l.attributes; t.length;) l.removeAttributeNode(t[0]);
    ei(l);
  }
  var St = new Map(),
    em = new Set();
  function Rn(l) {
    return typeof l.getRootNode == "function"
      ? l.getRootNode()
      : l.nodeType === 9
        ? l
        : l.ownerDocument;
  }
  var $t = p.d;
  p.d = { f: Zh, r: Vh, D: Lh, C: Kh, L: Jh, m: wh, X: $h, S: Wh, M: kh };
  function Zh() {
    var l = $t.f(),
      t = An();
    return l || t;
  }
  function Vh(l) {
    var t = ka(l);
    t !== null && t.tag === 5 && t.type === "form" ? zo(t) : $t.r(l);
  }
  var Ne = typeof document > "u" ? null : document;
  function um(l, t, a) {
    var e = Ne;
    if (e && typeof t == "string" && t) {
      var u = ot(t);
      ((u = 'link[rel="' + l + '"][href="' + u + '"]'),
        typeof a == "string" && (u += '[crossorigin="' + a + '"]'),
        em.has(u) ||
          (em.add(u),
          (l = { rel: l, crossOrigin: a, href: t }),
          e.querySelector(u) === null &&
            ((t = e.createElement("link")), Rl(t, "link", l), Ol(t), e.head.appendChild(t))));
    }
  }
  function Lh(l) {
    ($t.D(l), um("dns-prefetch", l, null));
  }
  function Kh(l, t) {
    ($t.C(l, t), um("preconnect", l, t));
  }
  function Jh(l, t, a) {
    $t.L(l, t, a);
    var e = Ne;
    if (e && l && t) {
      var u = 'link[rel="preload"][as="' + ot(t) + '"]';
      t === "image" && a && a.imageSrcSet
        ? ((u += '[imagesrcset="' + ot(a.imageSrcSet) + '"]'),
          typeof a.imageSizes == "string" && (u += '[imagesizes="' + ot(a.imageSizes) + '"]'))
        : (u += '[href="' + ot(l) + '"]');
      var n = u;
      switch (t) {
        case "style":
          n = De(l);
          break;
        case "script":
          n = Ue(l);
      }
      St.has(n) ||
        ((l = B(
          { rel: "preload", href: t === "image" && a && a.imageSrcSet ? void 0 : l, as: t },
          a,
        )),
        St.set(n, l),
        e.querySelector(u) !== null ||
          (t === "style" && e.querySelector(bu(n))) ||
          (t === "script" && e.querySelector(zu(n))) ||
          ((t = e.createElement("link")), Rl(t, "link", l), Ol(t), e.head.appendChild(t)));
    }
  }
  function wh(l, t) {
    $t.m(l, t);
    var a = Ne;
    if (a && l) {
      var e = t && typeof t.as == "string" ? t.as : "script",
        u = 'link[rel="modulepreload"][as="' + ot(e) + '"][href="' + ot(l) + '"]',
        n = u;
      switch (e) {
        case "audioworklet":
        case "paintworklet":
        case "serviceworker":
        case "sharedworker":
        case "worker":
        case "script":
          n = Ue(l);
      }
      if (
        !St.has(n) &&
        ((l = B({ rel: "modulepreload", href: l }, t)), St.set(n, l), a.querySelector(u) === null)
      ) {
        switch (e) {
          case "audioworklet":
          case "paintworklet":
          case "serviceworker":
          case "sharedworker":
          case "worker":
          case "script":
            if (a.querySelector(zu(n))) return;
        }
        ((e = a.createElement("link")), Rl(e, "link", l), Ol(e), a.head.appendChild(e));
      }
    }
  }
  function Wh(l, t, a) {
    $t.S(l, t, a);
    var e = Ne;
    if (e && l) {
      var u = Fa(e).hoistableStyles,
        n = De(l);
      t = t || "default";
      var i = u.get(n);
      if (!i) {
        var c = { loading: 0, preload: null };
        if ((i = e.querySelector(bu(n)))) c.loading = 5;
        else {
          ((l = B({ rel: "stylesheet", href: l, "data-precedence": t }, a)),
            (a = St.get(n)) && af(l, a));
          var f = (i = e.createElement("link"));
          (Ol(f),
            Rl(f, "link", l),
            (f._p = new Promise(function (y, g) {
              ((f.onload = y), (f.onerror = g));
            })),
            f.addEventListener("load", function () {
              c.loading |= 1;
            }),
            f.addEventListener("error", function () {
              c.loading |= 2;
            }),
            (c.loading |= 4),
            xn(i, t, e));
        }
        ((i = { type: "stylesheet", instance: i, count: 1, state: c }), u.set(n, i));
      }
    }
  }
  function $h(l, t) {
    $t.X(l, t);
    var a = Ne;
    if (a && l) {
      var e = Fa(a).hoistableScripts,
        u = Ue(l),
        n = e.get(u);
      n ||
        ((n = a.querySelector(zu(u))),
        n ||
          ((l = B({ src: l, async: !0 }, t)),
          (t = St.get(u)) && ef(l, t),
          (n = a.createElement("script")),
          Ol(n),
          Rl(n, "link", l),
          a.head.appendChild(n)),
        (n = { type: "script", instance: n, count: 1, state: null }),
        e.set(u, n));
    }
  }
  function kh(l, t) {
    $t.M(l, t);
    var a = Ne;
    if (a && l) {
      var e = Fa(a).hoistableScripts,
        u = Ue(l),
        n = e.get(u);
      n ||
        ((n = a.querySelector(zu(u))),
        n ||
          ((l = B({ src: l, async: !0, type: "module" }, t)),
          (t = St.get(u)) && ef(l, t),
          (n = a.createElement("script")),
          Ol(n),
          Rl(n, "link", l),
          a.head.appendChild(n)),
        (n = { type: "script", instance: n, count: 1, state: null }),
        e.set(u, n));
    }
  }
  function nm(l, t, a, e) {
    var u = (u = L.current) ? Rn(u) : null;
    if (!u) throw Error(d(446));
    switch (l) {
      case "meta":
      case "title":
        return null;
      case "style":
        return typeof a.precedence == "string" && typeof a.href == "string"
          ? ((t = De(a.href)),
            (a = Fa(u).hoistableStyles),
            (e = a.get(t)),
            e || ((e = { type: "style", instance: null, count: 0, state: null }), a.set(t, e)),
            e)
          : { type: "void", instance: null, count: 0, state: null };
      case "link":
        if (
          a.rel === "stylesheet" &&
          typeof a.href == "string" &&
          typeof a.precedence == "string"
        ) {
          l = De(a.href);
          var n = Fa(u).hoistableStyles,
            i = n.get(l);
          if (
            (i ||
              ((u = u.ownerDocument || u),
              (i = {
                type: "stylesheet",
                instance: null,
                count: 0,
                state: { loading: 0, preload: null },
              }),
              n.set(l, i),
              (n = u.querySelector(bu(l))) && !n._p && ((i.instance = n), (i.state.loading = 5)),
              St.has(l) ||
                ((a = {
                  rel: "preload",
                  as: "style",
                  href: a.href,
                  crossOrigin: a.crossOrigin,
                  integrity: a.integrity,
                  media: a.media,
                  hrefLang: a.hrefLang,
                  referrerPolicy: a.referrerPolicy,
                }),
                St.set(l, a),
                n || Fh(u, l, a, i.state))),
            t && e === null)
          )
            throw Error(d(528, ""));
          return i;
        }
        if (t && e !== null) throw Error(d(529, ""));
        return null;
      case "script":
        return (
          (t = a.async),
          (a = a.src),
          typeof a == "string" && t && typeof t != "function" && typeof t != "symbol"
            ? ((t = Ue(a)),
              (a = Fa(u).hoistableScripts),
              (e = a.get(t)),
              e || ((e = { type: "script", instance: null, count: 0, state: null }), a.set(t, e)),
              e)
            : { type: "void", instance: null, count: 0, state: null }
        );
      default:
        throw Error(d(444, l));
    }
  }
  function De(l) {
    return 'href="' + ot(l) + '"';
  }
  function bu(l) {
    return 'link[rel="stylesheet"][' + l + "]";
  }
  function im(l) {
    return B({}, l, { "data-precedence": l.precedence, precedence: null });
  }
  function Fh(l, t, a, e) {
    l.querySelector('link[rel="preload"][as="style"][' + t + "]")
      ? (e.loading = 1)
      : ((t = l.createElement("link")),
        (e.preload = t),
        t.addEventListener("load", function () {
          return (e.loading |= 1);
        }),
        t.addEventListener("error", function () {
          return (e.loading |= 2);
        }),
        Rl(t, "link", a),
        Ol(t),
        l.head.appendChild(t));
  }
  function Ue(l) {
    return '[src="' + ot(l) + '"]';
  }
  function zu(l) {
    return "script[async]" + l;
  }
  function cm(l, t, a) {
    if ((t.count++, t.instance === null))
      switch (t.type) {
        case "style":
          var e = l.querySelector('style[data-href~="' + ot(a.href) + '"]');
          if (e) return ((t.instance = e), Ol(e), e);
          var u = B({}, a, {
            "data-href": a.href,
            "data-precedence": a.precedence,
            href: null,
            precedence: null,
          });
          return (
            (e = (l.ownerDocument || l).createElement("style")),
            Ol(e),
            Rl(e, "style", u),
            xn(e, a.precedence, l),
            (t.instance = e)
          );
        case "stylesheet":
          u = De(a.href);
          var n = l.querySelector(bu(u));
          if (n) return ((t.state.loading |= 4), (t.instance = n), Ol(n), n);
          ((e = im(a)),
            (u = St.get(u)) && af(e, u),
            (n = (l.ownerDocument || l).createElement("link")),
            Ol(n));
          var i = n;
          return (
            (i._p = new Promise(function (c, f) {
              ((i.onload = c), (i.onerror = f));
            })),
            Rl(n, "link", e),
            (t.state.loading |= 4),
            xn(n, a.precedence, l),
            (t.instance = n)
          );
        case "script":
          return (
            (n = Ue(a.src)),
            (u = l.querySelector(zu(n)))
              ? ((t.instance = u), Ol(u), u)
              : ((e = a),
                (u = St.get(n)) && ((e = B({}, a)), ef(e, u)),
                (l = l.ownerDocument || l),
                (u = l.createElement("script")),
                Ol(u),
                Rl(u, "link", e),
                l.head.appendChild(u),
                (t.instance = u))
          );
        case "void":
          return null;
        default:
          throw Error(d(443, t.type));
      }
    else
      t.type === "stylesheet" &&
        (t.state.loading & 4) === 0 &&
        ((e = t.instance), (t.state.loading |= 4), xn(e, a.precedence, l));
    return t.instance;
  }
  function xn(l, t, a) {
    for (
      var e = a.querySelectorAll('link[rel="stylesheet"][data-precedence],style[data-precedence]'),
        u = e.length ? e[e.length - 1] : null,
        n = u,
        i = 0;
      i < e.length;
      i++
    ) {
      var c = e[i];
      if (c.dataset.precedence === t) n = c;
      else if (n !== u) break;
    }
    n
      ? n.parentNode.insertBefore(l, n.nextSibling)
      : ((t = a.nodeType === 9 ? a.head : a), t.insertBefore(l, t.firstChild));
  }
  function af(l, t) {
    (l.crossOrigin == null && (l.crossOrigin = t.crossOrigin),
      l.referrerPolicy == null && (l.referrerPolicy = t.referrerPolicy),
      l.title == null && (l.title = t.title));
  }
  function ef(l, t) {
    (l.crossOrigin == null && (l.crossOrigin = t.crossOrigin),
      l.referrerPolicy == null && (l.referrerPolicy = t.referrerPolicy),
      l.integrity == null && (l.integrity = t.integrity));
  }
  var Cn = null;
  function fm(l, t, a) {
    if (Cn === null) {
      var e = new Map(),
        u = (Cn = new Map());
      u.set(a, e);
    } else ((u = Cn), (e = u.get(a)), e || ((e = new Map()), u.set(a, e)));
    if (e.has(l)) return e;
    for (e.set(l, null), a = a.getElementsByTagName(l), u = 0; u < a.length; u++) {
      var n = a[u];
      if (
        !(n[qe] || n[Dl] || (l === "link" && n.getAttribute("rel") === "stylesheet")) &&
        n.namespaceURI !== "http://www.w3.org/2000/svg"
      ) {
        var i = n.getAttribute(t) || "";
        i = l + i;
        var c = e.get(i);
        c ? c.push(n) : e.set(i, [n]);
      }
    }
    return e;
  }
  function sm(l, t, a) {
    ((l = l.ownerDocument || l),
      l.head.insertBefore(a, t === "title" ? l.querySelector("head > title") : null));
  }
  function Ih(l, t, a) {
    if (a === 1 || t.itemProp != null) return !1;
    switch (l) {
      case "meta":
      case "title":
        return !0;
      case "style":
        if (typeof t.precedence != "string" || typeof t.href != "string" || t.href === "") break;
        return !0;
      case "link":
        if (
          typeof t.rel != "string" ||
          typeof t.href != "string" ||
          t.href === "" ||
          t.onLoad ||
          t.onError
        )
          break;
        return t.rel === "stylesheet"
          ? ((l = t.disabled), typeof t.precedence == "string" && l == null)
          : !0;
      case "script":
        if (
          t.async &&
          typeof t.async != "function" &&
          typeof t.async != "symbol" &&
          !t.onLoad &&
          !t.onError &&
          t.src &&
          typeof t.src == "string"
        )
          return !0;
    }
    return !1;
  }
  function om(l) {
    return !(l.type === "stylesheet" && (l.state.loading & 3) === 0);
  }
  function Ph(l, t, a, e) {
    if (
      a.type === "stylesheet" &&
      (typeof e.media != "string" || matchMedia(e.media).matches !== !1) &&
      (a.state.loading & 4) === 0
    ) {
      if (a.instance === null) {
        var u = De(e.href),
          n = t.querySelector(bu(u));
        if (n) {
          ((t = n._p),
            t !== null &&
              typeof t == "object" &&
              typeof t.then == "function" &&
              (l.count++, (l = qn.bind(l)), t.then(l, l)),
            (a.state.loading |= 4),
            (a.instance = n),
            Ol(n));
          return;
        }
        ((n = t.ownerDocument || t),
          (e = im(e)),
          (u = St.get(u)) && af(e, u),
          (n = n.createElement("link")),
          Ol(n));
        var i = n;
        ((i._p = new Promise(function (c, f) {
          ((i.onload = c), (i.onerror = f));
        })),
          Rl(n, "link", e),
          (a.instance = n));
      }
      (l.stylesheets === null && (l.stylesheets = new Map()),
        l.stylesheets.set(a, t),
        (t = a.state.preload) &&
          (a.state.loading & 3) === 0 &&
          (l.count++,
          (a = qn.bind(l)),
          t.addEventListener("load", a),
          t.addEventListener("error", a)));
    }
  }
  var uf = 0;
  function ly(l, t) {
    return (
      l.stylesheets && l.count === 0 && Yn(l, l.stylesheets),
      0 < l.count || 0 < l.imgCount
        ? function (a) {
            var e = setTimeout(function () {
              if ((l.stylesheets && Yn(l, l.stylesheets), l.unsuspend)) {
                var n = l.unsuspend;
                ((l.unsuspend = null), n());
              }
            }, 6e4 + t);
            0 < l.imgBytes && uf === 0 && (uf = 62500 * xh());
            var u = setTimeout(
              function () {
                if (
                  ((l.waitingForImages = !1),
                  l.count === 0 && (l.stylesheets && Yn(l, l.stylesheets), l.unsuspend))
                ) {
                  var n = l.unsuspend;
                  ((l.unsuspend = null), n());
                }
              },
              (l.imgBytes > uf ? 50 : 800) + t,
            );
            return (
              (l.unsuspend = a),
              function () {
                ((l.unsuspend = null), clearTimeout(e), clearTimeout(u));
              }
            );
          }
        : null
    );
  }
  function qn() {
    if ((this.count--, this.count === 0 && (this.imgCount === 0 || !this.waitingForImages))) {
      if (this.stylesheets) Yn(this, this.stylesheets);
      else if (this.unsuspend) {
        var l = this.unsuspend;
        ((this.unsuspend = null), l());
      }
    }
  }
  var Bn = null;
  function Yn(l, t) {
    ((l.stylesheets = null),
      l.unsuspend !== null &&
        (l.count++, (Bn = new Map()), t.forEach(ty, l), (Bn = null), qn.call(l)));
  }
  function ty(l, t) {
    if (!(t.state.loading & 4)) {
      var a = Bn.get(l);
      if (a) var e = a.get(null);
      else {
        ((a = new Map()), Bn.set(l, a));
        for (
          var u = l.querySelectorAll("link[data-precedence],style[data-precedence]"), n = 0;
          n < u.length;
          n++
        ) {
          var i = u[n];
          (i.nodeName === "LINK" || i.getAttribute("media") !== "not all") &&
            (a.set(i.dataset.precedence, i), (e = i));
        }
        e && a.set(null, e);
      }
      ((u = t.instance),
        (i = u.getAttribute("data-precedence")),
        (n = a.get(i) || e),
        n === e && a.set(null, u),
        a.set(i, u),
        this.count++,
        (e = qn.bind(this)),
        u.addEventListener("load", e),
        u.addEventListener("error", e),
        n
          ? n.parentNode.insertBefore(u, n.nextSibling)
          : ((l = l.nodeType === 9 ? l.head : l), l.insertBefore(u, l.firstChild)),
        (t.state.loading |= 4));
    }
  }
  var _u = {
    $$typeof: xl,
    Provider: null,
    Consumer: null,
    _currentValue: Y,
    _currentValue2: Y,
    _threadCount: 0,
  };
  function ay(l, t, a, e, u, n, i, c, f) {
    ((this.tag = 1),
      (this.containerInfo = l),
      (this.pingCache = this.current = this.pendingChildren = null),
      (this.timeoutHandle = -1),
      (this.callbackNode =
        this.next =
        this.pendingContext =
        this.context =
        this.cancelPendingCommit =
          null),
      (this.callbackPriority = 0),
      (this.expirationTimes = Pn(-1)),
      (this.entangledLanes =
        this.shellSuspendCounter =
        this.errorRecoveryDisabledLanes =
        this.expiredLanes =
        this.warmLanes =
        this.pingedLanes =
        this.suspendedLanes =
        this.pendingLanes =
          0),
      (this.entanglements = Pn(0)),
      (this.hiddenUpdates = Pn(null)),
      (this.identifierPrefix = e),
      (this.onUncaughtError = u),
      (this.onCaughtError = n),
      (this.onRecoverableError = i),
      (this.pooledCache = null),
      (this.pooledCacheLanes = 0),
      (this.formState = f),
      (this.incompleteTransitions = new Map()));
  }
  function mm(l, t, a, e, u, n, i, c, f, y, g, _) {
    return (
      (l = new ay(l, t, a, i, f, y, g, _, c)),
      (t = 1),
      n === !0 && (t |= 24),
      (n = at(3, null, null, t)),
      (l.current = n),
      (n.stateNode = l),
      (t = Bi()),
      t.refCount++,
      (l.pooledCache = t),
      t.refCount++,
      (n.memoizedState = { element: e, isDehydrated: a, cache: t }),
      Qi(n),
      l
    );
  }
  function dm(l) {
    return l ? ((l = ce), l) : ce;
  }
  function hm(l, t, a, e, u, n) {
    ((u = dm(u)),
      e.context === null ? (e.context = u) : (e.pendingContext = u),
      (e = ia(t)),
      (e.payload = { element: a }),
      (n = n === void 0 ? null : n),
      n !== null && (e.callback = n),
      (a = ca(l, e, t)),
      a !== null && ($l(a, l, t), Pe(a, l, t)));
  }
  function ym(l, t) {
    if (((l = l.memoizedState), l !== null && l.dehydrated !== null)) {
      var a = l.retryLane;
      l.retryLane = a !== 0 && a < t ? a : t;
    }
  }
  function nf(l, t) {
    (ym(l, t), (l = l.alternate) && ym(l, t));
  }
  function vm(l) {
    if (l.tag === 13 || l.tag === 31) {
      var t = Ua(l, 67108864);
      (t !== null && $l(t, l, 67108864), nf(l, 67108864));
    }
  }
  function rm(l) {
    if (l.tag === 13 || l.tag === 31) {
      var t = ct();
      t = li(t);
      var a = Ua(l, t);
      (a !== null && $l(a, l, t), nf(l, t));
    }
  }
  var Gn = !0;
  function ey(l, t, a, e) {
    var u = S.T;
    S.T = null;
    var n = p.p;
    try {
      ((p.p = 2), cf(l, t, a, e));
    } finally {
      ((p.p = n), (S.T = u));
    }
  }
  function uy(l, t, a, e) {
    var u = S.T;
    S.T = null;
    var n = p.p;
    try {
      ((p.p = 8), cf(l, t, a, e));
    } finally {
      ((p.p = n), (S.T = u));
    }
  }
  function cf(l, t, a, e) {
    if (Gn) {
      var u = ff(e);
      if (u === null) (Jc(l, t, e, Xn, a), Sm(l, e));
      else if (iy(u, l, t, a, e)) e.stopPropagation();
      else if ((Sm(l, e), t & 4 && -1 < ny.indexOf(l))) {
        for (; u !== null;) {
          var n = ka(u);
          if (n !== null)
            switch (n.tag) {
              case 3:
                if (((n = n.stateNode), n.current.memoizedState.isDehydrated)) {
                  var i = pa(n.pendingLanes);
                  if (i !== 0) {
                    var c = n;
                    for (c.pendingLanes |= 2, c.entangledLanes |= 2; i;) {
                      var f = 1 << (31 - lt(i));
                      ((c.entanglements[1] |= f), (i &= ~f));
                    }
                    (Dt(n), (P & 6) === 0 && ((Tn = Il() + 500), vu(0)));
                  }
                }
                break;
              case 31:
              case 13:
                ((c = Ua(n, 2)), c !== null && $l(c, n, 2), An(), nf(n, 2));
            }
          if (((n = ff(e)), n === null && Jc(l, t, e, Xn, a), n === u)) break;
          u = n;
        }
        u !== null && e.stopPropagation();
      } else Jc(l, t, e, null, a);
    }
  }
  function ff(l) {
    return ((l = si(l)), sf(l));
  }
  var Xn = null;
  function sf(l) {
    if (((Xn = null), (l = $a(l)), l !== null)) {
      var t = V(l);
      if (t === null) l = null;
      else {
        var a = t.tag;
        if (a === 13) {
          if (((l = vl(t)), l !== null)) return l;
          l = null;
        } else if (a === 31) {
          if (((l = Nl(t)), l !== null)) return l;
          l = null;
        } else if (a === 3) {
          if (t.stateNode.current.memoizedState.isDehydrated)
            return t.tag === 3 ? t.stateNode.containerInfo : null;
          l = null;
        } else t !== l && (l = null);
      }
    }
    return ((Xn = l), null);
  }
  function gm(l) {
    switch (l) {
      case "beforetoggle":
      case "cancel":
      case "click":
      case "close":
      case "contextmenu":
      case "copy":
      case "cut":
      case "auxclick":
      case "dblclick":
      case "dragend":
      case "dragstart":
      case "drop":
      case "focusin":
      case "focusout":
      case "input":
      case "invalid":
      case "keydown":
      case "keypress":
      case "keyup":
      case "mousedown":
      case "mouseup":
      case "paste":
      case "pause":
      case "play":
      case "pointercancel":
      case "pointerdown":
      case "pointerup":
      case "ratechange":
      case "reset":
      case "resize":
      case "seeked":
      case "submit":
      case "toggle":
      case "touchcancel":
      case "touchend":
      case "touchstart":
      case "volumechange":
      case "change":
      case "selectionchange":
      case "textInput":
      case "compositionstart":
      case "compositionend":
      case "compositionupdate":
      case "beforeblur":
      case "afterblur":
      case "beforeinput":
      case "blur":
      case "fullscreenchange":
      case "focus":
      case "hashchange":
      case "popstate":
      case "select":
      case "selectstart":
        return 2;
      case "drag":
      case "dragenter":
      case "dragexit":
      case "dragleave":
      case "dragover":
      case "mousemove":
      case "mouseout":
      case "mouseover":
      case "pointermove":
      case "pointerout":
      case "pointerover":
      case "scroll":
      case "touchmove":
      case "wheel":
      case "mouseenter":
      case "mouseleave":
      case "pointerenter":
      case "pointerleave":
        return 8;
      case "message":
        switch (Lm()) {
          case Af:
            return 2;
          case pf:
            return 8;
          case Nu:
          case Km:
            return 32;
          case Of:
            return 268435456;
          default:
            return 32;
        }
      default:
        return 32;
    }
  }
  var of = !1,
    Sa = null,
    ba = null,
    za = null,
    Tu = new Map(),
    Eu = new Map(),
    _a = [],
    ny =
      "mousedown mouseup touchcancel touchend touchstart auxclick dblclick pointercancel pointerdown pointerup dragend dragstart drop compositionend compositionstart keydown keypress keyup input textInput copy cut paste click change contextmenu reset".split(
        " ",
      );
  function Sm(l, t) {
    switch (l) {
      case "focusin":
      case "focusout":
        Sa = null;
        break;
      case "dragenter":
      case "dragleave":
        ba = null;
        break;
      case "mouseover":
      case "mouseout":
        za = null;
        break;
      case "pointerover":
      case "pointerout":
        Tu.delete(t.pointerId);
        break;
      case "gotpointercapture":
      case "lostpointercapture":
        Eu.delete(t.pointerId);
    }
  }
  function Au(l, t, a, e, u, n) {
    return l === null || l.nativeEvent !== n
      ? ((l = {
          blockedOn: t,
          domEventName: a,
          eventSystemFlags: e,
          nativeEvent: n,
          targetContainers: [u],
        }),
        t !== null && ((t = ka(t)), t !== null && vm(t)),
        l)
      : ((l.eventSystemFlags |= e),
        (t = l.targetContainers),
        u !== null && t.indexOf(u) === -1 && t.push(u),
        l);
  }
  function iy(l, t, a, e, u) {
    switch (t) {
      case "focusin":
        return ((Sa = Au(Sa, l, t, a, e, u)), !0);
      case "dragenter":
        return ((ba = Au(ba, l, t, a, e, u)), !0);
      case "mouseover":
        return ((za = Au(za, l, t, a, e, u)), !0);
      case "pointerover":
        var n = u.pointerId;
        return (Tu.set(n, Au(Tu.get(n) || null, l, t, a, e, u)), !0);
      case "gotpointercapture":
        return ((n = u.pointerId), Eu.set(n, Au(Eu.get(n) || null, l, t, a, e, u)), !0);
    }
    return !1;
  }
  function bm(l) {
    var t = $a(l.target);
    if (t !== null) {
      var a = V(t);
      if (a !== null) {
        if (((t = a.tag), t === 13)) {
          if (((t = vl(a)), t !== null)) {
            ((l.blockedOn = t),
              jf(l.priority, function () {
                rm(a);
              }));
            return;
          }
        } else if (t === 31) {
          if (((t = Nl(a)), t !== null)) {
            ((l.blockedOn = t),
              jf(l.priority, function () {
                rm(a);
              }));
            return;
          }
        } else if (t === 3 && a.stateNode.current.memoizedState.isDehydrated) {
          l.blockedOn = a.tag === 3 ? a.stateNode.containerInfo : null;
          return;
        }
      }
    }
    l.blockedOn = null;
  }
  function Qn(l) {
    if (l.blockedOn !== null) return !1;
    for (var t = l.targetContainers; 0 < t.length;) {
      var a = ff(l.nativeEvent);
      if (a === null) {
        a = l.nativeEvent;
        var e = new a.constructor(a.type, a);
        ((fi = e), a.target.dispatchEvent(e), (fi = null));
      } else return ((t = ka(a)), t !== null && vm(t), (l.blockedOn = a), !1);
      t.shift();
    }
    return !0;
  }
  function zm(l, t, a) {
    Qn(l) && a.delete(t);
  }
  function cy() {
    ((of = !1),
      Sa !== null && Qn(Sa) && (Sa = null),
      ba !== null && Qn(ba) && (ba = null),
      za !== null && Qn(za) && (za = null),
      Tu.forEach(zm),
      Eu.forEach(zm));
  }
  function Zn(l, t) {
    l.blockedOn === t &&
      ((l.blockedOn = null),
      of || ((of = !0), b.unstable_scheduleCallback(b.unstable_NormalPriority, cy)));
  }
  var Vn = null;
  function _m(l) {
    Vn !== l &&
      ((Vn = l),
      b.unstable_scheduleCallback(b.unstable_NormalPriority, function () {
        Vn === l && (Vn = null);
        for (var t = 0; t < l.length; t += 3) {
          var a = l[t],
            e = l[t + 1],
            u = l[t + 2];
          if (typeof e != "function") {
            if (sf(e || a) === null) continue;
            break;
          }
          var n = ka(a);
          n !== null &&
            (l.splice(t, 3),
            (t -= 3),
            cc(n, { pending: !0, data: u, method: a.method, action: e }, e, u));
        }
      }));
  }
  function He(l) {
    function t(f) {
      return Zn(f, l);
    }
    (Sa !== null && Zn(Sa, l),
      ba !== null && Zn(ba, l),
      za !== null && Zn(za, l),
      Tu.forEach(t),
      Eu.forEach(t));
    for (var a = 0; a < _a.length; a++) {
      var e = _a[a];
      e.blockedOn === l && (e.blockedOn = null);
    }
    for (; 0 < _a.length && ((a = _a[0]), a.blockedOn === null);)
      (bm(a), a.blockedOn === null && _a.shift());
    if (((a = (l.ownerDocument || l).$$reactFormReplay), a != null))
      for (e = 0; e < a.length; e += 3) {
        var u = a[e],
          n = a[e + 1],
          i = u[Vl] || null;
        if (typeof n == "function") i || _m(a);
        else if (i) {
          var c = null;
          if (n && n.hasAttribute("formAction")) {
            if (((u = n), (i = n[Vl] || null))) c = i.formAction;
            else if (sf(u) !== null) continue;
          } else c = i.action;
          (typeof c == "function" ? (a[e + 1] = c) : (a.splice(e, 3), (e -= 3)), _m(a));
        }
      }
  }
  function Tm() {
    function l(n) {
      n.canIntercept &&
        n.info === "react-transition" &&
        n.intercept({
          handler: function () {
            return new Promise(function (i) {
              return (u = i);
            });
          },
          focusReset: "manual",
          scroll: "manual",
        });
    }
    function t() {
      (u !== null && (u(), (u = null)), e || setTimeout(a, 20));
    }
    function a() {
      if (!e && !navigation.transition) {
        var n = navigation.currentEntry;
        n &&
          n.url != null &&
          navigation.navigate(n.url, {
            state: n.getState(),
            info: "react-transition",
            history: "replace",
          });
      }
    }
    if (typeof navigation == "object") {
      var e = !1,
        u = null;
      return (
        navigation.addEventListener("navigate", l),
        navigation.addEventListener("navigatesuccess", t),
        navigation.addEventListener("navigateerror", t),
        setTimeout(a, 100),
        function () {
          ((e = !0),
            navigation.removeEventListener("navigate", l),
            navigation.removeEventListener("navigatesuccess", t),
            navigation.removeEventListener("navigateerror", t),
            u !== null && (u(), (u = null)));
        }
      );
    }
  }
  function mf(l) {
    this._internalRoot = l;
  }
  ((Ln.prototype.render = mf.prototype.render =
    function (l) {
      var t = this._internalRoot;
      if (t === null) throw Error(d(409));
      var a = t.current,
        e = ct();
      hm(a, e, l, t, null, null);
    }),
    (Ln.prototype.unmount = mf.prototype.unmount =
      function () {
        var l = this._internalRoot;
        if (l !== null) {
          this._internalRoot = null;
          var t = l.containerInfo;
          (hm(l.current, 2, null, l, null, null), An(), (t[Wa] = null));
        }
      }));
  function Ln(l) {
    this._internalRoot = l;
  }
  Ln.prototype.unstable_scheduleHydration = function (l) {
    if (l) {
      var t = Hf();
      l = { blockedOn: null, target: l, priority: t };
      for (var a = 0; a < _a.length && t !== 0 && t < _a[a].priority; a++);
      (_a.splice(a, 0, l), a === 0 && bm(l));
    }
  };
  var Em = N.version;
  if (Em !== "19.2.8") throw Error(d(527, Em, "19.2.8"));
  p.findDOMNode = function (l) {
    var t = l._reactInternals;
    if (t === void 0)
      throw typeof l.render == "function"
        ? Error(d(188))
        : ((l = Object.keys(l).join(",")), Error(d(268, l)));
    return ((l = E(t)), (l = l !== null ? ll(l) : null), (l = l === null ? null : l.stateNode), l);
  };
  var fy = {
    bundleType: 0,
    version: "19.2.8",
    rendererPackageName: "react-dom",
    currentDispatcherRef: S,
    reconcilerVersion: "19.2.8",
  };
  if (typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ < "u") {
    var Kn = __REACT_DEVTOOLS_GLOBAL_HOOK__;
    if (!Kn.isDisabled && Kn.supportsFiber)
      try {
        ((Re = Kn.inject(fy)), (Pl = Kn));
      } catch {}
  }
  return (
    (Ou.createRoot = function (l, t) {
      if (!q(l)) throw Error(d(299));
      var a = !1,
        e = "",
        u = Uo,
        n = Ho,
        i = jo;
      return (
        t != null &&
          (t.unstable_strictMode === !0 && (a = !0),
          t.identifierPrefix !== void 0 && (e = t.identifierPrefix),
          t.onUncaughtError !== void 0 && (u = t.onUncaughtError),
          t.onCaughtError !== void 0 && (n = t.onCaughtError),
          t.onRecoverableError !== void 0 && (i = t.onRecoverableError)),
        (t = mm(l, 1, !1, null, null, a, e, null, u, n, i, Tm)),
        (l[Wa] = t.current),
        Kc(l),
        new mf(t)
      );
    }),
    (Ou.hydrateRoot = function (l, t, a) {
      if (!q(l)) throw Error(d(299));
      var e = !1,
        u = "",
        n = Uo,
        i = Ho,
        c = jo,
        f = null;
      return (
        a != null &&
          (a.unstable_strictMode === !0 && (e = !0),
          a.identifierPrefix !== void 0 && (u = a.identifierPrefix),
          a.onUncaughtError !== void 0 && (n = a.onUncaughtError),
          a.onCaughtError !== void 0 && (i = a.onCaughtError),
          a.onRecoverableError !== void 0 && (c = a.onRecoverableError),
          a.formState !== void 0 && (f = a.formState)),
        (t = mm(l, 1, !0, t, a ?? null, e, u, f, n, i, c, Tm)),
        (t.context = dm(null)),
        (a = t.current),
        (e = ct()),
        (e = li(e)),
        (u = ia(e)),
        (u.callback = null),
        ca(a, u, e),
        (a = e),
        (t.current.lanes = a),
        Ce(t, a),
        Dt(t),
        (l[Wa] = t.current),
        Kc(l),
        new Ln(t)
      );
    }),
    (Ou.version = "19.2.8"),
    Ou
  );
}
var Rm;
function Sy() {
  if (Rm) return yf.exports;
  Rm = 1;
  function b() {
    if (!(
      typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ > "u" ||
      typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE != "function"
    ))
      try {
        __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(b);
      } catch (N) {
        console.error(N);
      }
  }
  return (b(), (yf.exports = gy()), yf.exports);
}
var by = Sy();
const zy = { normalText: 4.5, largeText: 3, nonText: 3 };
function _y(b) {
  const N = b.trim().replace(/^#/, "");
  if (!/^([0-9a-f]{3}|[0-9a-f]{6})$/i.test(N)) throw new Error(`Invalid hex colour: "${b}"`);
  const D =
    N.length === 3
      ? N.split("")
          .map((d) => d + d)
          .join("")
      : N;
  return {
    r: Number.parseInt(D.slice(0, 2), 16),
    g: Number.parseInt(D.slice(2, 4), 16),
    b: Number.parseInt(D.slice(4, 6), 16),
  };
}
function Sf(b) {
  const N = b / 255;
  return N <= 0.03928 ? N / 12.92 : Math.pow((N + 0.055) / 1.055, 2.4);
}
function xm(b) {
  const { r: N, g: D, b: d } = typeof b == "string" ? _y(b) : b;
  return 0.2126 * Sf(N) + 0.7152 * Sf(D) + 0.0722 * Sf(d);
}
function Ty(b, N) {
  const D = xm(b),
    d = xm(N),
    q = Math.max(D, d),
    V = Math.min(D, d);
  return (q + 0.05) / (V + 0.05);
}
function Ym(b) {
  var N,
    D,
    d = "";
  if (typeof b == "string" || typeof b == "number") d += b;
  else if (typeof b == "object")
    if (Array.isArray(b)) {
      var q = b.length;
      for (N = 0; N < q; N++) b[N] && (D = Ym(b[N])) && (d && (d += " "), (d += D));
    } else for (D in b) b[D] && (d && (d += " "), (d += D));
  return d;
}
function Gm() {
  for (var b, N, D = 0, d = "", q = arguments.length; D < q; D++)
    (b = arguments[D]) && (N = Ym(b)) && (d && (d += " "), (d += N));
  return d;
}
const Ey = "_button_jhv0s_1",
  Ay = "_sm_jhv0s_33",
  py = "_md_jhv0s_38",
  Oy = "_primary_jhv0s_45",
  My = "_secondary_jhv0s_59",
  Ny = "_ghost_jhv0s_73",
  bf = { button: Ey, sm: Ay, md: py, primary: Oy, secondary: My, ghost: Ny };
function kt({
  variant: b = "secondary",
  size: N = "md",
  loading: D = !1,
  disabled: d,
  className: q,
  children: V,
  type: vl = "button",
  ...Nl
}) {
  const R = d === !0 || D;
  return A.jsx("button", {
    type: vl,
    className: Gm(bf.button, bf[b], bf[N], q),
    disabled: R,
    "aria-busy": D || void 0,
    ...Nl,
    children: V,
  });
}
const Dy = "_badge_rx5f5_1",
  Uy = "_verified_rx5f5_20",
  Hy = "_observed_rx5f5_27",
  jy = "_suggested_rx5f5_34",
  Cm = { badge: Dy, verified: Uy, observed: Hy, suggested: jy },
  qm = { verified: "Verified", observed: "Observed", suggested: "Suggested" },
  Bm = {
    verified: "Taken directly from an unambiguous source, such as a merged pull request.",
    observed: "Drawn from clear discussion, or corroborated across more than one source.",
    suggested: "Inferred from a single source such as a meeting transcript. Worth checking.",
  };
function Ry({ certainty: b, className: N }) {
  return A.jsx("span", {
    className: Gm(Cm.badge, Cm[b], N),
    role: "img",
    title: Bm[b],
    "aria-label": `${qm[b]}: ${Bm[b]}`,
    children: qm[b],
  });
}
const yl = {
    0: "#ffffff",
    50: "#fafafa",
    100: "#f5f5f5",
    200: "#e5e5e5",
    300: "#d4d4d4",
    400: "#a3a3a3",
    500: "#737373",
    600: "#525252",
    700: "#404040",
    800: "#262626",
    900: "#171717",
    950: "#0a0a0a",
  },
  Jn = { light: "#1d4ed8", dark: "#60a5fa" },
  xy = {
    bg: { default: yl[0], subtle: yl[50], muted: yl[100], inverse: yl[950] },
    fg: { default: yl[950], muted: yl[600], subtle: yl[500], inverse: yl[0], onAccent: yl[0] },
    border: { default: yl[200], strong: yl[300], interactive: yl[500], focus: Jn.light },
    accent: { default: Jn.light },
  },
  Cy = {
    bg: { default: yl[950], subtle: yl[900], muted: yl[800], inverse: yl[0] },
    fg: { default: yl[50], muted: yl[400], subtle: yl[500], inverse: yl[950], onAccent: yl[950] },
    border: { default: yl[800], strong: yl[700], interactive: yl[500], focus: Jn.dark },
    accent: { default: Jn.dark },
  },
  qy = {
    0: "0",
    1: "0.25rem",
    2: "0.5rem",
    3: "0.75rem",
    4: "1rem",
    5: "1.25rem",
    6: "1.5rem",
    8: "2rem",
    10: "2.5rem",
    12: "3rem",
    16: "4rem",
    20: "5rem",
    24: "6rem",
  },
  Va = { xs: "0.75rem", sm: "0.875rem", base: "1rem", lg: "1.125rem", "2xl": "1.5rem" },
  La = { normal: 400, medium: 500, semibold: 600 },
  Ka = { tight: 1.25, normal: 1.5, relaxed: 1.65 },
  Ja = { tight: "-0.01em", normal: "0" },
  By = {
    prose: {
      fontSize: Va.base,
      lineHeight: Ka.relaxed,
      fontWeight: La.normal,
      letterSpacing: Ja.normal,
    },
    body: {
      fontSize: Va.base,
      lineHeight: Ka.normal,
      fontWeight: La.normal,
      letterSpacing: Ja.normal,
    },
    bodySmall: {
      fontSize: Va.sm,
      lineHeight: Ka.normal,
      fontWeight: La.normal,
      letterSpacing: Ja.normal,
    },
    label: {
      fontSize: Va.sm,
      lineHeight: Ka.tight,
      fontWeight: La.medium,
      letterSpacing: Ja.normal,
    },
    caption: {
      fontSize: Va.xs,
      lineHeight: Ka.normal,
      fontWeight: La.normal,
      letterSpacing: Ja.normal,
    },
    heading: {
      fontSize: Va["2xl"],
      lineHeight: Ka.tight,
      fontWeight: La.semibold,
      letterSpacing: Ja.tight,
    },
    subheading: {
      fontSize: Va.lg,
      lineHeight: Ka.tight,
      fontWeight: La.medium,
      letterSpacing: Ja.normal,
    },
  },
  Yy = "_page_12us7_13",
  Gy = "_header_12us7_19",
  Xy = "_title_12us7_29",
  Qy = "_subtitle_12us7_37",
  Zy = "_section_12us7_45",
  Vy = "_sectionTitle_12us7_49",
  Ly = "_sectionNote_12us7_56",
  Ky = "_row_12us7_64",
  Jy = "_stack_12us7_71",
  wy = "_specimen_12us7_77",
  Wy = "_specimenLabel_12us7_84",
  $y = "_grid_12us7_91",
  ky = "_swatch_12us7_99",
  Fy = "_swatchChip_12us7_105",
  Iy = "_swatchMeta_12us7_109",
  Py = "_swatchName_12us7_114",
  lv = "_swatchValue_12us7_120",
  tv = "_tableWrapper_12us7_130",
  av = "_table_12us7_130",
  ev = "_ratio_12us7_155",
  uv = "_pass_12us7_163",
  nv = "_fail_12us7_167",
  iv = "_specimenRow_12us7_175",
  cv = "_specimenName_12us7_188",
  fv = "_specimenText_12us7_195",
  sv = "_spaceRow_12us7_202",
  ov = "_spaceBar_12us7_208",
  mv = "_footer_12us7_214",
  j = {
    page: Yy,
    header: Gy,
    title: Xy,
    subtitle: Qy,
    section: Zy,
    sectionTitle: Vy,
    sectionNote: Ly,
    row: Ky,
    stack: Jy,
    specimen: wy,
    specimenLabel: Wy,
    grid: $y,
    swatch: ky,
    swatchChip: Fy,
    swatchMeta: Iy,
    swatchName: Py,
    swatchValue: lv,
    tableWrapper: tv,
    table: av,
    ratio: ev,
    pass: uv,
    fail: nv,
    specimenRow: iv,
    specimenName: cv,
    specimenText: fv,
    spaceRow: sv,
    spaceBar: ov,
    footer: mv,
  },
  dv = ["verified", "observed", "suggested"],
  hv = [
    { style: "heading", sample: "This week in engineering" },
    { style: "subheading", sample: "Authentication and tenant isolation" },
    {
      style: "prose",
      sample:
        "Priya finished the invitation flow and moved on to session revocation. The work on rate limiting is waiting on the API layer, which is the next thing to land.",
    },
    { style: "body", sample: "The quick brown fox jumps over the lazy dog." },
    { style: "bodySmall", sample: "The quick brown fox jumps over the lazy dog." },
    { style: "label", sample: "Workspace name" },
    { style: "caption", sample: "Updated 4 minutes ago" },
  ],
  yv = [
    { label: "Body text on background", fg: "default", requirement: "normalText" },
    { label: "Muted text on background", fg: "muted", requirement: "normalText" },
    { label: "Subtle text on background", fg: "subtle", requirement: "normalText" },
    { label: "Control outline", fg: "borderInteractive", requirement: "nonText" },
    { label: "Focus ring", fg: "accent", requirement: "nonText" },
  ];
function vv(b, N) {
  return N === "borderInteractive"
    ? b.border.interactive
    : N === "accent"
      ? b.accent.default
      : b.fg[N];
}
function rv() {
  const [b, N] = zf.useState("light");
  zf.useEffect(() => {
    document.documentElement.dataset.theme = b;
  }, [b]);
  const D = b === "light" ? xy : Cy;
  return A.jsxs("main", {
    className: j.page,
    children: [
      A.jsxs("header", {
        className: j.header,
        children: [
          A.jsxs("div", {
            children: [
              A.jsx("h1", { className: j.title, children: "CAIRN — Design System" }),
              A.jsx("p", {
                className: j.subtitle,
                children:
                  "Black and white, monochrome by decision rather than by default. Colour carries meaning, and meaning about people is what this product refuses to imply — so there is no success/warning/danger scale for anything describing someone’s work.",
              }),
            ],
          }),
          A.jsx(kt, {
            variant: "secondary",
            onClick: () => {
              N((d) => (d === "light" ? "dark" : "light"));
            },
            "aria-label": `Switch to ${b === "light" ? "dark" : "light"} theme`,
            children: b === "light" ? "Dark theme" : "Light theme",
          }),
        ],
      }),
      A.jsx(gv, { theme: D }),
      A.jsx(Sv, { theme: D }),
      A.jsx(bv, {}),
      A.jsx(zv, {}),
      A.jsx(_v, {}),
      A.jsx(Tv, {}),
      A.jsxs("footer", {
        className: j.footer,
        children: [
          "Every value on this page comes from ",
          A.jsx("code", { children: "src/tokens/" }),
          ". The stylesheet is generated from those tokens and checked for drift in CI, so a colour cannot pass its contrast test and ship as something else.",
        ],
      }),
    ],
  });
}
function gv({ theme: b }) {
  return A.jsxs("section", {
    className: j.section,
    children: [
      A.jsx("h2", { className: j.sectionTitle, children: "Contrast" }),
      A.jsx("p", {
        className: j.sectionNote,
        children:
          "Measured live from the tokens rendering this page, in the theme you are looking at. WCAG 2.1 AA is a locked requirement — the European Accessibility Act has been in force since June 2025 — so these are also asserted in the test suite. Shown here because a table someone can read is what makes the guarantee legible to a reviewer.",
      }),
      A.jsx("div", {
        className: j.tableWrapper,
        children: A.jsxs("table", {
          className: j.table,
          children: [
            A.jsx("thead", {
              children: A.jsxs("tr", {
                children: [
                  A.jsx("th", { scope: "col", children: "Pair" }),
                  A.jsx("th", { scope: "col", children: "Ratio" }),
                  A.jsx("th", { scope: "col", children: "Required" }),
                  A.jsx("th", { scope: "col", children: "Result" }),
                ],
              }),
            }),
            A.jsx("tbody", {
              children: yv.map((N) => {
                const D = Ty(vv(b, N.fg), b.bg.default),
                  d = zy[N.requirement],
                  q = D >= d;
                return A.jsxs(
                  "tr",
                  {
                    children: [
                      A.jsx("th", { scope: "row", children: N.label }),
                      A.jsxs("td", { className: j.ratio, children: [D.toFixed(2), ":1"] }),
                      A.jsxs("td", { className: j.ratio, children: [d, ":1"] }),
                      A.jsx("td", {
                        className: q ? j.pass : j.fail,
                        children: q ? "Passes AA" : "Fails AA",
                      }),
                    ],
                  },
                  N.label,
                );
              }),
            }),
          ],
        }),
      }),
    ],
  });
}
function Sv({ theme: b }) {
  const N = Object.entries(b).flatMap(([D, d]) =>
    Object.entries(d).map(([q, V]) => ({ name: `${D}.${q}`, value: V })),
  );
  return A.jsxs("section", {
    className: j.section,
    children: [
      A.jsx("h2", { className: j.sectionTitle, children: "Colour roles" }),
      A.jsxs("p", {
        className: j.sectionNote,
        children: [
          "Roles, not colours. Components reference ",
          A.jsx("code", { children: "fg.default" }),
          ", never a grey step, so changing a theme never means touching a component. Note that",
          " ",
          A.jsx("code", { children: "border.default" }),
          " is deliberately low-contrast: a hairline dividing two sections carries no information, while the outline of an input carries essential information — only the latter is held to 3:1.",
        ],
      }),
      A.jsx("div", {
        className: j.grid,
        children: N.map((D) =>
          A.jsxs(
            "div",
            {
              className: j.swatch,
              children: [
                A.jsx("div", { className: j.swatchChip, style: { background: D.value } }),
                A.jsxs("div", {
                  className: j.swatchMeta,
                  children: [
                    A.jsx("span", { className: j.swatchName, children: D.name }),
                    A.jsx("span", { className: j.swatchValue, children: D.value }),
                  ],
                }),
              ],
            },
            D.name,
          ),
        ),
      }),
    ],
  });
}
function bv() {
  return A.jsxs("section", {
    className: j.section,
    children: [
      A.jsx("h2", { className: j.sectionTitle, children: "Typography" }),
      A.jsxs("p", {
        className: j.sectionNote,
        children: [
          "CAIRN’s primary output is prose someone reads rather than scans, which makes typography load-bearing rather than decorative. Sizes are in ",
          A.jsx("code", { children: "rem" }),
          " so they respect the reader’s browser setting; a ",
          A.jsx("code", { children: "px" }),
          " scale silently breaks zoom for anyone who has increased their default, and looks fine to everyone testing at defaults.",
        ],
      }),
      A.jsx("div", {
        className: j.specimen,
        children: hv.map((b) =>
          A.jsxs(
            "div",
            {
              className: j.specimenRow,
              children: [
                A.jsx("span", { className: j.specimenName, children: b.style }),
                A.jsx("span", {
                  className: j.specimenText,
                  style: By[b.style],
                  children: b.sample,
                }),
              ],
            },
            b.style,
          ),
        ),
      }),
    ],
  });
}
function zv() {
  return A.jsxs("section", {
    className: j.section,
    children: [
      A.jsx("h2", { className: j.sectionTitle, children: "Buttons" }),
      A.jsxs("p", {
        className: j.sectionNote,
        children: [
          "Three variants. There is no ",
          A.jsx("code", { children: "danger" }),
          " variant — destructive actions are distinguished by confirmation flow and wording, not by turning a button red, which is the only way to keep a palette that carries no semantic colour.",
        ],
      }),
      A.jsxs("div", {
        className: j.stack,
        children: [
          A.jsxs("div", {
            className: j.specimen,
            children: [
              A.jsx("p", { className: j.specimenLabel, children: "variant" }),
              A.jsxs("div", {
                className: j.row,
                children: [
                  A.jsx(kt, { variant: "primary", children: "Primary" }),
                  A.jsx(kt, { variant: "secondary", children: "Secondary" }),
                  A.jsx(kt, { variant: "ghost", children: "Ghost" }),
                ],
              }),
            ],
          }),
          A.jsxs("div", {
            className: j.specimen,
            children: [
              A.jsx("p", { className: j.specimenLabel, children: "size" }),
              A.jsxs("div", {
                className: j.row,
                children: [
                  A.jsx(kt, { size: "sm", children: "Small" }),
                  A.jsx(kt, { size: "md", children: "Medium" }),
                ],
              }),
            ],
          }),
          A.jsxs("div", {
            className: j.specimen,
            children: [
              A.jsx("p", { className: j.specimenLabel, children: "state" }),
              A.jsxs("div", {
                className: j.row,
                children: [
                  A.jsx(kt, { variant: "primary", disabled: !0, children: "Disabled" }),
                  A.jsx(kt, { variant: "primary", loading: !0, children: "Saving" }),
                  A.jsx(kt, { variant: "secondary", loading: !0, children: "Saving" }),
                ],
              }),
              A.jsxs("p", {
                className: j.subtitle,
                children: [
                  "The loading state sets ",
                  A.jsx("code", { children: "aria-busy" }),
                  " and keeps its label rather than swapping in a spinner, so a screen reader user is told the control is working instead of hearing its name vanish. Tab to these — the focus ring is the one place this system spends colour, because a monochrome interface otherwise fails WCAG 2.4.7.",
                ],
              }),
            ],
          }),
        ],
      }),
    ],
  });
}
function _v() {
  return A.jsxs("section", {
    className: j.section,
    children: [
      A.jsx("h2", { className: j.sectionTitle, children: "Certainty" }),
      A.jsx("p", {
        className: j.sectionNote,
        children:
          "The most product-specific component here. A GitHub assignment is unambiguous; a commitment inferred from a meeting transcript carries roughly 30% speaker-misattribution risk. Presenting both with equal authority is the fastest way to lose a user’s trust for good.",
      }),
      A.jsx("p", {
        className: j.sectionNote,
        children:
          "Traffic-light colouring would be the only colour in the system, drawing the eye to uncertainty rather than content — and amber reads as a judgement about the person, not about the evidence. Tiers differ by weight and border instead, which survives greyscale and colour-blindness with no extra work. There are no percentages: “73% confident” looks rigorous, means nothing to a non-technical reader, and invites false precision.",
      }),
      A.jsx("div", {
        className: j.specimen,
        children: A.jsx("div", {
          className: j.row,
          children: dv.map((b) => A.jsx(Ry, { certainty: b }, b)),
        }),
      }),
    ],
  });
}
function Tv() {
  return A.jsxs("section", {
    className: j.section,
    children: [
      A.jsx("h2", { className: j.sectionTitle, children: "Spacing" }),
      A.jsx("p", {
        className: j.sectionNote,
        children:
          "A 4px base, applied consistently. A single rhythm is what makes an interface feel considered; arbitrary values are what make it feel improvised.",
      }),
      A.jsx("div", {
        className: j.specimen,
        children: Object.entries(qy)
          .filter(([b]) => b !== "0")
          .map(([b, N]) =>
            A.jsxs(
              "div",
              {
                className: j.specimenRow,
                children: [
                  A.jsxs("span", { className: j.specimenName, children: ["space.", b, " · ", N] }),
                  A.jsx("div", {
                    className: j.spaceRow,
                    children: A.jsx("div", { className: j.spaceBar, style: { width: N } }),
                  }),
                ],
              },
              b,
            ),
          ),
      }),
    ],
  });
}
const Xm = document.getElementById("root");
if (Xm === null) throw new Error("No #root element — index.html and main.tsx have diverged");
by.createRoot(Xm).render(A.jsx(zf.StrictMode, { children: A.jsx(rv, {}) }));
