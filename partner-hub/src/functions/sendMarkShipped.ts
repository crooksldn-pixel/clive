import { sendMarkShipped } from "../handlers/sendMarkShipped.ts";
import { serve } from "../lib/runtime.ts";

serve(sendMarkShipped);
