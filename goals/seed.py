import json

from sqlalchemy import select

from storage.models import Goal

GOAL_SEEDS = [
    {
        "category": "llm-internals",
        "description": (
            "Understand transformer internals well enough to reason about "
            "and modify architecture choices"
        ),
        "priority": 1,
        "concept_requirements": [
            "self-attention",
            "multi-head attention",
            "scaled dot-product attention",
            "positional encoding",
            "encoder-decoder architecture",
            "beam search",
            "byte-pair encoding",
            "KV cache key-value cache",
            "RoPE rotary positional embeddings",
            "GQA grouped query attention",
            "flash attention",
            "layer normalization placement",
            "MoE mixture of experts",
            "speculative decoding",
        ],
    },
    {
        "category": "training",
        "description": (
            "Be able to fine-tune and evaluate small models, including the "
            "phase-2 cross-encoder"
        ),
        "priority": 1,
        "concept_requirements": [
            "LoRA low-rank adaptation",
            "QLoRA quantized low-rank adaptation",
            "PEFT parameter-efficient fine-tuning",
            "RLHF reinforcement learning from human feedback",
            "DPO direct preference optimization",
            "knowledge distillation",
            "cross-encoder training",
            "contrastive learning",
            "learning rate scheduling",
            "gradient accumulation",
            "mixed precision training",
            "checkpoint averaging",
            "evaluation benchmark design",
            "training data curation",
        ],
    },
    {
        "category": "agentic-systems",
        "description": "Build and evaluate retrieval-augmented agent pipelines",
        "priority": 1,
        "concept_requirements": [
            "RAG retrieval-augmented generation",
            "vector database",
            "embedding models",
            "chunking strategies",
            "reranking",
            "hybrid search",
            "tool calling",
            "structured output constraints",
            "graph-based agent orchestration",
            "agent evaluation",
            "context window management",
            "prompt engineering",
            "human-in-the-loop gates",
            "semantic similarity search",
        ],
    },
    {
        "category": "inference",
        "description": (
            "Run and optimize models locally, and package them for distribution"
        ),
        "priority": 1,
        "concept_requirements": [
            "quantization",
            "GGUF model format",
            "llama.cpp",
            "model serving",
            "continuous batching",
            "GPU memory management",
            "CUDA compute unified device architecture",
            "inference latency optimization",
            "KV cache key-value cache",
            "speculative decoding",
            "ONNX open neural network exchange",
            "model distillation for deployment",
            "desktop application packaging",
            "TFLOPS trillion floating point operations per second",
        ],
    },
    {
        "category": "software-engineering",
        "description": (
            "Ship and operate services on AWS with sound engineering practice"
        ),
        "priority": 1,
        "concept_requirements": [
            "AWS Lambda serverless functions",
            "containerization with Docker",
            "IaC infrastructure as code",
            "CI/CD continuous integration and deployment pipelines",
            "AWS S3 simple storage service",
            "IAM identity and access management",
            "database migrations",
            "observability and tracing",
            "API design",
            "message queues",
            "system design",
            "integration testing strategy",
            "AWS ECS elastic container service",
            "secrets management",
        ],
    },
]


def seed_goals(session) -> list[Goal]:
    existing = {goal.category: goal for goal in session.scalars(select(Goal))}

    goals = []
    for seed in GOAL_SEEDS:
        goal = existing.get(seed["category"])
        if goal is None:
            goal = Goal(
                description=seed["description"],
                category=seed["category"],
                priority=seed["priority"],
                concept_requirements=json.dumps(seed["concept_requirements"]),
            )
            session.add(goal)
        goals.append(goal)

    session.commit()
    return goals
