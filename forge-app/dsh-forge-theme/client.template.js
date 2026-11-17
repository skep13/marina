// Generated into lib/client.js by build.py — edit this template or build.py, not lib/client.js.
window.__ModuleLoader__.load({
	id: "dsh-forge-theme",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		const { jsx, jsxs } = require("react/jsx-runtime");

		const TOKENS = /*TOKENS*/;
		const CSS = /*CSS*/;
		// Claude-style greeting by time of day; picked once per page load.
		const NAME = "Jacob";
		const GREETINGS = {
			night:     ["Hello, night owl", "Up late, " + NAME + "?", "Back at it, " + NAME],
			morning:   ["Good morning, " + NAME, "Back at it, " + NAME, "What's new, " + NAME + "?"],
			afternoon: ["Good afternoon, " + NAME, "Back at it, " + NAME, "How's your day going, " + NAME + "?"],
			evening:   ["Good evening, " + NAME, "Back at it, " + NAME, "How was your day, " + NAME + "?"]
		};
		const hour = new Date().getHours();
		const slot = hour < 5 ? "night" : hour < 12 ? "morning" : hour < 18 ? "afternoon" : hour < 23 ? "evening" : "night";
		const HEADLINE = GREETINGS[slot][Math.floor(Math.random() * GREETINGS[slot].length)];

		// Flame mark (sidebar + start screen). Same paths as the splash emblem
		// and macos/make_icon.py.
		const FLAME_OUTER = "M12 1.8 C12.9 5.2 15.6 7.0 17.4 9.6 C18.6 11.3 19.2 13.2 19.2 15.2 C19.2 19.3 16.0 22.4 12.0 22.4 C8.0 22.4 4.8 19.3 4.8 15.4 C4.8 12.9 6.0 10.9 7.7 9.4 C7.8 11.0 8.5 12.3 9.6 13.0 C9.2 8.9 10.4 5.0 12.0 1.8 Z";
		const FLAME_INNER = "M12.3 10.6 C12.8 13.0 14.4 14.2 15.2 15.8 C15.6 16.5 15.8 17.2 15.8 17.9 C15.8 20.0 14.1 21.5 12.0 21.5 C9.9 21.5 8.2 20.0 8.2 18.0 C8.2 16.6 8.9 15.5 9.9 14.8 C10.0 15.7 10.4 16.4 11.0 16.8 C10.8 14.6 11.3 12.4 12.3 10.6 Z";
		function ForgeMark({ size }) {
			const s = typeof size === "number" ? size : 22;
			return jsxs("svg", { width: s, height: s, viewBox: "0 0 24 24", "aria-hidden": true, children: [
				jsxs("defs", { children: [
					jsxs("linearGradient", { id: "forge-flame-outer", x1: 0, y1: 0, x2: 0, y2: 1, children: [
						jsx("stop", { offset: "0%", stopColor: "#ffb257" }),
						jsx("stop", { offset: "55%", stopColor: "#ff7a2f" }),
						jsx("stop", { offset: "100%", stopColor: "#c2410c" })
					] }),
					jsxs("linearGradient", { id: "forge-flame-inner", x1: 0, y1: 0, x2: 0, y2: 1, children: [
						jsx("stop", { offset: "0%", stopColor: "#ffd08a" }),
						jsx("stop", { offset: "100%", stopColor: "#fff1d6" })
					] })
				] }),
				jsx("path", { d: FLAME_OUTER, fill: "url(#forge-flame-outer)" }),
				jsx("path", { d: FLAME_INNER, fill: "url(#forge-flame-inner)" })
			] });
		}

		// FORGE wordmark with the splash's heat gradient.
		function ForgeName() {
			return jsx("span", {
				style: {
					font: '800 20px/1 "Avenir Next Condensed", "Avenir Next", "Helvetica Neue", sans-serif',
					letterSpacing: "0.05em", textTransform: "uppercase", paddingTop: "2px",
					background: "linear-gradient(180deg, #f1e9dc 30%, #ffb257 75%, #c2410c 100%)",
					WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent"
				},
				children: "Forge"
			});
		}

		const inject = ["theme", "slots"];
		function apply(ctx) {
			// Palette (both schemes get the forge values) + force DSH's dark mode.
			ctx.effect(() => ctx.theme.overrideTokens("dsh-forge-theme", TOKENS));
			try { ctx.theme.setTheme("dark"); } catch (e) {}
			const forceDark = () => { if (!document.body.hasAttribute("data-ds-dark-theme")) document.body.setAttribute("data-ds-dark-theme", ""); };
			forceDark();
			const bodyObs = new MutationObserver(forceDark);
			bodyObs.observe(document.body, { attributes: true, attributeFilter: ["data-ds-dark-theme"] });

			// Forge styling that tokens can't express.
			const style = document.createElement("style");
			style.id = "dsh-forge-theme";
			style.textContent = CSS;
			document.head.appendChild(style);

			// Sparks rising off the hearth. Every 3rd one only flies while Forge is working.
			const sparks = document.createElement("div");
			sparks.id = "forge-sparks";
			sparks.setAttribute("aria-hidden", "true");
			for (let i = 0; i < 36; i++) {
				const s = document.createElement("i");
				if (i % 3 === 2) s.className = "f-busy";
				const size = 1.5 + Math.random() * 2.5;
				s.style.left = (30 + Math.random() * 55) + "%";
				s.style.width = s.style.height = size + "px";
				s.style.setProperty("--dx", ((Math.random() - 0.4) * 180).toFixed(0) + "px");
				s.style.animationDuration = (5 + Math.random() * 7).toFixed(2) + "s";
				s.style.animationDelay = (-Math.random() * 12).toFixed(2) + "s";
				sparks.appendChild(s);
			}
			document.body.appendChild(sparks);

			// Tab title + start-screen headline.
			const fix = () => {
				if (document.title.includes("DeepSeek Harness")) document.title = document.title.replace("DeepSeek Harness", "Forge");
				for (const el of document.querySelectorAll('[class*="_titleGroup"] > span:first-child')) {
					if (el.textContent !== HEADLINE) el.textContent = HEADLINE;
				}
			};
			fix();
			const domObs = new MutationObserver(fix);
			domObs.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
			ctx.effect(() => () => { bodyObs.disconnect(); domObs.disconnect(); style.remove(); sparks.remove(); });

			ctx.slots.inject("sidebar.brand.mark", () => ctx.slots.inject("sidebar.brand.name", function* () {
				yield ctx.slots.register({ name: "sidebar.brand.mark" }, ForgeMark);
				yield ctx.slots.register({ name: "sidebar.brand.name" }, ForgeName);
			}));
			ctx.slots.inject("conversation.hero.brand.mark", function* () {
				yield ctx.slots.register({ name: "conversation.hero.brand.mark" }, ForgeMark);
			});
		}
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
