import { useEffect, useRef, type RefObject } from "react";
import { useRouter } from "@tanstack/react-router";

/**
 * One behaviour for every error screen: go back to the previous entry when
 * there is one, otherwise land on the files page. Never `history.back()` out of
 * the app on a deep link (the browser would leave AURA entirely), and never a
 * full page reload (which loses whatever the shell still holds).
 */
export function useSafeBack(): () => void {
  const router = useRouter();
  return () => {
    if (router.history.canGoBack()) {
      router.history.back();
    } else {
      void router.navigate({ to: "/" });
    }
  };
}

/**
 * Move focus to the error heading. The element that triggered the crash is
 * gone, so without this the focus falls back to `<body>`: a keyboard user then
 * restarts from the top of the document with no idea where they are. Pair it
 * with `tabIndex={-1}` on the heading.
 */
export function useErrorHeadingFocus<T extends HTMLElement>(): RefObject<T> {
  const ref = useRef<T>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return ref;
}
