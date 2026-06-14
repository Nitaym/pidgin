import { Link, useNavigate } from "react-router-dom";
import { useApp } from "../context/AppContext";

function SpecialistIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MarketplaceIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M3 9h18M3 9l1.5-5h15L21 9M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ScratchIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function HireEntryPage() {
  const navigate = useNavigate();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";

  const options = [
    {
      key: "specialist",
      icon: <SpecialistIcon />,
      title: "Consult a specialist",
      desc: "Talk it through with HR. Describe what you need and get a recommendation.",
      onClick: () => navigate(`/${slug}/agents/hr/chat`),
    },
    {
      key: "marketplace",
      icon: <MarketplaceIcon />,
      title: "Choose from marketplace",
      desc: "Browse ready-made candidate profiles and hire one in a couple of clicks.",
      onClick: () => navigate(`/${slug}/hire/marketplace`),
    },
    {
      key: "scratch",
      icon: <ScratchIcon />,
      title: "Write a profile from scratch",
      desc: "Define the role yourself — mission, responsibilities, and the rest.",
      onClick: () => navigate(`/${slug}/hire/marketplace?fresh=1`),
    },
  ];

  return (
    <div className="hire-entry page-enter">
      <div className="hire-entry-inner">
        <Link to=".." className="ghost hire-entry-back">
          ← Team
        </Link>
        <h1 className="hire-entry-question">What position are you looking to hire?</h1>
        <p className="hire-entry-sub">Pick how you'd like to start.</p>

        <div className="hire-entry-options">
          {options.map((opt) => (
            <button key={opt.key} type="button" className="hire-entry-card" onClick={opt.onClick}>
              <span className="hire-entry-card-icon">{opt.icon}</span>
              <span className="hire-entry-card-title">{opt.title}</span>
              <span className="hire-entry-card-desc">{opt.desc}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
