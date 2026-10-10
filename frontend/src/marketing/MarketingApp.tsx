import { Navigate, Route, Routes } from "react-router-dom";
import { AiDemoPage, DemoDisclosurePage, MarketingContactPage, MarketingHome, MarketingLayout } from "./MarketingPages";

export default function MarketingApp() {
  return <Routes>
    <Route element={<MarketingLayout />}>
      <Route path="/" element={<MarketingHome />} />
      <Route path="/ai-demo" element={<AiDemoPage />} />
      <Route path="/contact" element={<MarketingContactPage />} />
      <Route path="/demo-disclosure" element={<DemoDisclosurePage />} />
    </Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}
