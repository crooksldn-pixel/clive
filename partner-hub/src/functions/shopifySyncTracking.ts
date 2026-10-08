import { shopifySyncTracking } from "../handlers/shopifySyncTracking.ts";
import { serve } from "../lib/runtime.ts";

serve(shopifySyncTracking);
