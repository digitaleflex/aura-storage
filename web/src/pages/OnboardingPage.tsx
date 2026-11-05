import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useAuth } from "../lib/auth";
import { ONBOARDING_STEPS, markOnboardingSeen } from "../lib/onboarding";
import { VaultMark } from "../components/VaultMark";

export function OnboardingPage() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [stepIndex, setStepIndex] = useState(0);

  const step = ONBOARDING_STEPS[stepIndex];
  if (!step) return null;
  const isLast = stepIndex === ONBOARDING_STEPS.length - 1;

  function handleNext() {
    if (isLast) {
      // Dernière étape : marquer comme vu et aller aux fichiers
      markOnboardingSeen();
      navigate({ to: "/" });
    } else {
      setStepIndex((i) => i + 1);
    }
  }

  function handleSkip() {
    markOnboardingSeen();
    navigate({ to: "/" });
  }

  function handleLogout() {
    void logout();
    navigate({ to: "/login" });
  }

  const progress = ((stepIndex + 1) / ONBOARDING_STEPS.length) * 100;

  return (
    <div className="onboarding-page" data-testid="onboarding-page">
      <div className="onboarding-shell">
        <VaultMark size={32} />
        <div className="onboarding-card">
          <div className="onboarding-header">
            <h1>Bienvenue dans AURA Vault</h1>
            <p className="onboarding-subtitle">
              Vos fichiers, chiffrés et sécurisés
            </p>
          </div>

          <div className="onboarding-progress">
            <div className="onboarding-progress-track">
              <div
                className="onboarding-progress-bar"
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="onboarding-progress-text">
              {stepIndex + 1} / {ONBOARDING_STEPS.length}
            </span>
          </div>

          <div className="onboarding-step">
            <div className="onboarding-step-icon">
              {step.id === "import" && "📥"}
              {step.id === "share" && "🔗"}
              {step.id === "trash" && "🗑️"}
              {step.id === "done" && "✅"}
            </div>
            <div className="onboarding-step-content">
              <h2>{step.title}</h2>
              <p>{step.description}</p>
            </div>
          </div>

          <div className="onboarding-actions">
            {!isLast && (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                onClick={handleSkip}
              >
                Passer l'introduction
              </button>
            )}
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleNext}
            >
              {isLast ? "Commencer" : step.action}
            </button>
          </div>

          <div className="onboarding-footer">
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={handleLogout}
            >
              Se déconnecter
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
