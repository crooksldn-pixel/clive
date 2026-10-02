/*
 * Checkout Kit ships TypeScript source, not declarations, so its files are
 * type-checked with ours. It calls V8's Error.captureStackTrace behind an
 * existence check; Hermes has it too. Declared here so tsc knows it.
 */
interface ErrorConstructor {
  captureStackTrace?(target: object, constructorOpt?: Function): void;
}
