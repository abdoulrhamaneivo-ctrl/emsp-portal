import { defineConfig } from "@neon/config/v1";

export default defineConfig({
  buckets: {
    "candidate-documents": { access: "private" },
  },
});
