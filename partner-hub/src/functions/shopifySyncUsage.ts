import { shopifySyncUsage } from "../handlers/shopifySyncUsage.ts";
import { serve } from "../lib/runtime.ts";

serve(shopifySyncUsage);
