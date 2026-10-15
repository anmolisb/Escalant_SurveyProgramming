import { useEffect, useState } from "react";

/** Routes live in the URL hash, so every page has its own link and the
 *  browser's back button works, with no server routing needed. */
export type Route =
  | { page: "home" }
  | { page: "how" }
  | { page: "new" }
  | { page: "survey"; name: string; section: string };

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "surveys" && parts[1]) return { page: "survey", name: parts[1], section: parts[2] ?? "overview" };
  if (parts[0] === "how-it-works") return { page: "how" };
  if (parts[0] === "new") return { page: "new" };
  return { page: "home" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => { setRoute(parse(window.location.hash)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const link = {
  home: "#/",
  how: "#/how-it-works",
  new: "#/new",
  survey: (name: string, section = "overview") =>
    `#/surveys/${encodeURIComponent(name)}${section === "overview" ? "" : `/${section}`}`,
};
