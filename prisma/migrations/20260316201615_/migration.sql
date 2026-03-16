-- DropForeignKey
ALTER TABLE "AiAnalysis" DROP CONSTRAINT "AiAnalysis_logId_fkey";

-- AlterTable
ALTER TABLE "AiAnalysis" ADD COLUMN     "status" TEXT NOT NULL DEFAULT 'processing',
ALTER COLUMN "summary" DROP NOT NULL,
ALTER COLUMN "learning_score" DROP NOT NULL;

-- AddForeignKey
ALTER TABLE "AiAnalysis" ADD CONSTRAINT "AiAnalysis_logId_fkey" FOREIGN KEY ("logId") REFERENCES "Log"("id") ON DELETE CASCADE ON UPDATE CASCADE;
