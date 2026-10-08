import { shopifyCheckConnection } from "../handlers/shopifyCheckConnection.ts";
import { serve } from "../lib/runtime.ts";

serve(shopifyCheckConnection);
