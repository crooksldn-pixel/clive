import { shopifyCreateDiscount } from "../handlers/shopifyCreateDiscount.ts";
import { serve } from "../lib/runtime.ts";

serve(shopifyCreateDiscount);
