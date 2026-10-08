import { shopifyCreateSend } from "../handlers/shopifyCreateSend.ts";
import { serve } from "../lib/runtime.ts";

serve(shopifyCreateSend);
