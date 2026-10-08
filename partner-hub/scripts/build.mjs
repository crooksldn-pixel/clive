// Bundles each src/functions/<name>.ts into a self-contained
// base44/functions/<name>/entry.ts, the layout `npx base44 functions deploy`
// reads. Each entry file can also be pasted into the Base44 dashboard as-is.
import { build } from "esbuild";
import { readdir, mkdir, writeFile, rm } from "node:fs/promises";
import { dirname, join, basename } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = join(root, "src", "functions");
const outDir = join(root, "base44", "functions");

const names = (await readdir(srcDir)).filter((f) => f.endsWith(".ts")).map((f) => basename(f, ".ts")).sort();
await rm(outDir, { recursive: true, force: true });

for (const name of names) {
  const dir = join(outDir, name);
  await mkdir(dir, { recursive: true });
  const result = await build({
    entryPoints: [join(srcDir, `${name}.ts`)],
    bundle: true,
    write: false,
    format: "esm",
    platform: "neutral",
    target: "es2022",
    external: ["npm:*"],
    charset: "utf8",
    legalComments: "none",
    banner: {
      js:
        `// CROOKS Partner Hub — Base44 function "${name}".\n` +
        "// GENERATED from partner-hub/src by `npm run build`. Edit the source, not this file.\n",
    },
  });
  await writeFile(join(dir, "entry.ts"), result.outputFiles[0].text);
  await writeFile(join(dir, "function.jsonc"), JSON.stringify({ name, entry: "entry.ts" }, null, 2) + "\n");
  console.log(`built ${name} (${(result.outputFiles[0].text.length / 1024).toFixed(1)} KB)`);
}
