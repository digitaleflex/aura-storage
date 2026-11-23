// ESLint (flat config). Philosophie : le filet est posé sans changer le
// comportement de l'application.
//
//  - « error » : règles qui passent déjà sur tout le code. Elles bloquent la CI
//    (`npm run lint`), donc elles ne peuvent plus régresser. `rules-of-hooks`
//    aurait attrapé le plantage de la page Partages (hook après un return).
//  - « warn »  : règles qui trouvent encore des cas. Elles sont comptées et
//    réduites petit à petit ; elles ne bloquent pas.
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "storybook-static/**",
      "playwright-report/**",
      "test-results/**",
      "src/stories/**",
      "*.config.ts",
      "pw.local.config.ts",
      // Script de capture d'écran documenté, pas du code applicatif.
      "capture-transfers.cjs",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}", "e2e/**/*.ts"],
    languageOptions: {
      ecmaVersion: 2023,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      // Bloquantes : une erreur ici est un vrai bug (ordre des hooks).
      "react-hooks/rules-of-hooks": "error",
      // Avertissement : dépendances d'effets oubliées.
      "react-hooks/exhaustive-deps": "warn",

      // Les règles « recommandées » de typescript-eslint qui trouvent encore des
      // cas passent en avertissement (voir le compte dans la sortie de la CI).
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-expressions": "warn",
      "@typescript-eslint/no-empty-object-type": "warn",
      "no-empty": ["warn", { allowEmptyCatch: true }],
      "no-useless-escape": "warn",
      "no-control-regex": "warn",
      "prefer-const": "warn",
      // Règle d'ESLint 10 : relancer une erreur sans `cause` perd la trace d'origine.
      "preserve-caught-error": "warn",
    },
  },
);
