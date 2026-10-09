import { syncPromotions } from "../handlers/syncPromotions.ts";
import { serve } from "../lib/runtime.ts";

serve(syncPromotions);
