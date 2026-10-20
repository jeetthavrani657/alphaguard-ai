import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * If a page fails while it is being drawn (a bad value, or a page file that could not be loaded), React would otherwise leave
 * a blank screen. This catches it and shows a plain message with a way out. The navigation above it keeps working.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("A page failed to draw:", error, info.componentStack);   // for whoever opens the browser's console
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="crash" role="alert">
        <h1>Something went wrong on this page</h1>
        <p>
          The rest of the app is fine. Try loading the page again; if it keeps happening, go back to the home page and open the page from there.
        </p>
        <p>
          <button className="btn primary" onClick={() => window.location.reload()}>Reload this page</button>{" "}
          <a className="btn" href="/">Go to the home page</a>
        </p>
      </div>
    );
  }
}
