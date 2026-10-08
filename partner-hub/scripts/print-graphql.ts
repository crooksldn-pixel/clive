// Prints every Shopify operation the functions run, for re-validation
// against a newer Admin API version.
import { ALL_OPERATIONS } from "../src/lib/queries.ts";

for (const [name, doc] of Object.entries(ALL_OPERATIONS)) {
  console.log(`# ${name}${doc}\n`);
}
