import os
from openai import AsyncOpenAI

from pydantic import BaseModel


client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class LogEntry(BaseModel):
    title: str
    content: str
    tags: list[str]


class SummaryResult(BaseModel):
    summary: str
    key_points: list[str]
    suggested_tags: list[str]
    learning_score: int


systemPrompt = """
You are an AI learning analysis agent.

You receive learning logs with:
title: string
content: string
tags: string[]

Analyze the log and produce useful learning insights.

Return ONLY valid JSON:

{
"summary": "1-2 sentence clear summary",
"key_points": ["3-5 concrete learning points"],
"suggested_tags": ["relevant technical tags"],
"learning_score": 0-10
}

Do NOT:
- include explanations outside JSON
- generate generic AI filler text
- repeat the same idea multiple times
- invent information not present in the log
- copy the log content directly

Focus on concise, practical learning insights.
"""


async def generate_summary(data: LogEntry) -> SummaryResult:
    response = await client.responses.parse(
        model="gpt-4o",
        instructions=systemPrompt,
        input=data.model_dump_json(),
        max_output_tokens=150,
        temperature=0.5,
        text_format=SummaryResult,
    )
    return response.output_parsed


# print(
#     asyncio.run(
#         generate_summary(
#             LogEntry(
#                 title="Learned about FastAPI",
#                 content="Today I learned how to use FastAPI for building APIs. It was really easy to set up and has great documentation. I created a simple API with a few endpoints and it worked perfectly.",
#                 tags=["fastapi", "python", "web development"],
#             )
#         )
#     )
# )
