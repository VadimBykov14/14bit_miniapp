import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { AccessCode } from "./components/AccessCode";
import { applyTheme } from "./lib/bridge";
import { blockNativeDrag } from "./lib/gesture";
import { applyPalette } from "./lib/palette";
import { watchScreens } from "./lib/screens";
import "./index.css";

applyTheme();
applyPalette();
blockNativeDrag();
watchScreens();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AccessCode>
      <App />
    </AccessCode>
  </StrictMode>,
);
