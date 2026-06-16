/**
 * Page components barrel export
 *
 * Each page wraps a step (or group of steps) in the Migration Wizard.
 */
export { default as ConnectPage } from "./connect";
export type { ConnectPageProps } from "./connect";

export { default as DiscoveryPage } from "./discovery";
export type { DiscoveryPageProps } from "./discovery";

export { default as StrategyPage } from "./strategy";
export type { StrategyPageProps } from "./strategy";

export { default as ModernizationPage } from "./modernization";
export type { ModernizationPageProps } from "./modernization";

export { default as ResultPage } from "./result";
export type { ResultPageProps } from "./result";

export { default as LandingPage } from "./landing/LandingPage";
export { default as AuthCallback } from "./auth/AuthCallback";
