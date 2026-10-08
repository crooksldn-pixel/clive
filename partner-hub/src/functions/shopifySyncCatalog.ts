import { shopifySyncCatalog } from "../handlers/shopifySyncCatalog.ts";
import { serve } from "../lib/runtime.ts";

serve(shopifySyncCatalog);
