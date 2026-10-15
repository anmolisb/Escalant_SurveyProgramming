import { HowItWorks } from "./pages/HowItWorks";
import { Home } from "./pages/Home";
import { NewSurvey } from "./pages/NewSurvey";
import { Survey } from "./pages/Survey";
import { link, useRoute } from "./router";

export default function App() {
  const route = useRoute();
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <a className="wordmark" href={link.home}>Survey QA</a>
          <nav aria-label="Main">
            <a href={link.home} aria-current={route.page === "home" || route.page === "survey" ? "page" : undefined}>Surveys</a>
            <a href={link.new} aria-current={route.page === "new" ? "page" : undefined}>Check a questionnaire</a>
            <a href={link.how} aria-current={route.page === "how" ? "page" : undefined}>How it works</a>
          </nav>
        </div>
      </header>
      <main>
        {route.page === "home" && <Home />}
        {route.page === "how" && <HowItWorks />}
        {route.page === "new" && <NewSurvey />}
        {route.page === "survey" && <Survey name={route.name} section={route.section} />}
      </main>
    </>
  );
}
