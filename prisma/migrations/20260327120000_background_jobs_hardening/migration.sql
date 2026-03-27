-- AlterTable
ALTER TABLE "AiAnalysis"
ADD COLUMN     "retryCount" INTEGER NOT NULL DEFAULT 0,
ADD COLUMN     "lastError" TEXT,
ADD COLUMN     "processingStartedAt" TIMESTAMP(3),
ADD COLUMN     "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
ALTER COLUMN "status" SET DEFAULT 'queued',
ALTER COLUMN "key_points" SET DEFAULT ARRAY[]::TEXT[],
ALTER COLUMN "suggested_tags" SET DEFAULT ARRAY[]::TEXT[];

-- Backfill existing rows
UPDATE "AiAnalysis"
SET "updatedAt" = CURRENT_TIMESTAMP
WHERE "updatedAt" IS NULL;

UPDATE "AiAnalysis"
SET "status" = 'queued'
WHERE "status" = 'processing' AND "summary" IS NULL;
