import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../src/styles/theme.css";
import { Preview } from "./Preview.js";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("No #root element — index.html and main.tsx have diverged");
}

createRoot(container).render(
  <StrictMode>
    <Preview />
  </StrictMode>,
);
