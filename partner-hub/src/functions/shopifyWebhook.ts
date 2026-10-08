import { shopifyWebhook } from "../handlers/shopifyWebhook.ts";
import { serve } from "../lib/runtime.ts";

serve(shopifyWebhook);
