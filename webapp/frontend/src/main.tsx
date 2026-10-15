import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";

// The browser loads index.html, which loads this file, which mounts <App />
// into <div id="root">. BrowserRouter makes the address bar part of the app:
// changing the URL changes which page component is shown, without a reload.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
