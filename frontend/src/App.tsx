import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import DealShell from "./pages/DealShell";
import AuditLog from "./pages/deal/AuditLog";
import Documents from "./pages/deal/Documents";
import Investors from "./pages/deal/Investors";
import Research from "./pages/deal/Research";
import Review from "./pages/deal/Review";
import Leads from "./pages/Leads";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/leads" element={<Leads />} />
        <Route path="/deals/:dealId" element={<DealShell />}>
          <Route index element={<Navigate to="review" replace />} />
          <Route path="review" element={<Review />} />
          <Route path="research" element={<Research />} />
          <Route path="documents" element={<Documents />} />
          <Route path="investors" element={<Investors />} />
          <Route path="audit-log" element={<AuditLog />} />
        </Route>
      </Route>
    </Routes>
  );
}
