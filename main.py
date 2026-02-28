"""CLI entry point for the Ditto Synthetic Matchmaking Feedback Loop Simulator."""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import config
from src.persona_generator.generator import PersonaGenerator
from src.orchestrator.engine import SimulationEngine
from src.llm.client import get_llm_client


def setup_logging(verbose: bool = False):
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def cmd_generate_personas(args):
    """Generate synthetic personas."""
    logger = logging.getLogger("main")
    logger.info(f"Generating {args.count} personas...")

    mongo_enabled = args.mongo or config.MONGODB_ENABLED
    generator = PersonaGenerator()
    output_path = Path(args.output) if args.output else None
    personas = generator.generate(
        count=args.count,
        batch_size=args.batch_size,
        output_path=output_path,
        mongo_enabled=mongo_enabled,
    )

    logger.info(f"✅ Generated {len(personas)} personas")

    # Print sample
    if args.preview:
        logger.info("\n📋 Sample personas:")
        for p in personas[:3]:
            logger.info(f"\n{p.to_profile_summary()}")
            logger.info(f"  Style: {p.communication_style.value} | Strictness: {p.preference_strictness.value}")


def cmd_run_simulation(args):
    """Run the matchmaking conversation simulation."""
    logger = logging.getLogger("main")

    # Load personas
    persona_path = Path(args.persona_file) if args.persona_file else None
    personas = PersonaGenerator.load_personas(persona_path)

    if len(personas) < 5:
        logger.error(
            f"Need at least 5 personas to run simulation (found {len(personas)}). "
            f"Run `python main.py generate-personas --count 20` first."
        )
        sys.exit(1)

    logger.info(f"Loaded {len(personas)} personas")

    # Initialize client (all Ollama)
    client = get_llm_client(model=args.model)
    mongo_enabled = args.mongo or config.MONGODB_ENABLED

    # Run simulation
    engine = SimulationEngine(
        persona_pool=personas,
        llm_client=client,
        mongo_enabled=mongo_enabled,
    )

    results = engine.run(num_conversations=args.num_conversations)

    logger.info(f"\n✅ Simulation complete! {len(results)} conversations logged.")
    logger.info(f"📁 Output: {engine.logger.log_file_path}")


def cmd_validate(args):
    """Validate generated JSONL conversation logs."""
    from src.orchestrator.logger import ConversationLogger
    from src.models.conversation import ConversationLog

    logger = logging.getLogger("main")
    path = Path(args.file)

    if not path.exists():
        logger.error(f"File not found: {path}")
        sys.exit(1)

    conversations = ConversationLogger.load_conversations(path)
    logger.info(f"Loaded {len(conversations)} conversations from {path}")

    # Validate
    errors = 0
    for i, conv in enumerate(conversations):
        issues = []
        if not conv.turns:
            issues.append("no turns")
        if not conv.persona:
            issues.append("no persona")
        if not conv.conversation_id:
            issues.append("no conversation_id")
        if conv.total_rounds == 0 and not conv.dropped_off:
            issues.append("0 rounds but not dropped off")

        if issues:
            logger.warning(f"  Conversation {i+1} ({conv.conversation_id[:8]}): {', '.join(issues)}")
            errors += 1

    if errors == 0:
        logger.info("✅ All conversations pass validation!")
    else:
        logger.warning(f"⚠️ {errors}/{len(conversations)} conversations have issues")

    # Summary stats
    accepted = sum(1 for c in conversations if c.rounds_to_acceptance is not None)
    dropped = sum(1 for c in conversations if c.dropped_off)
    ratings = [c.post_date_rating for c in conversations if c.post_date_rating is not None]

    logger.info(f"\n📊 Summary:")
    logger.info(f"  Total: {len(conversations)}")
    logger.info(f"  Accepted a match: {accepted} ({accepted/max(len(conversations),1):.0%})")
    logger.info(f"  Dropped off: {dropped}")
    if ratings:
        logger.info(f"  Avg post-date rating: {sum(ratings)/len(ratings):.1f}/5")


def cmd_sync_to_mongo(args):
    """Bulk sync existing JSONL files to MongoDB."""
    from src.storage.mongo_client import get_mongo_storage
    from src.orchestrator.logger import ConversationLogger

    logger = logging.getLogger("main")
    mongo = get_mongo_storage()

    # Sync personas
    persona_path = config.PERSONAS_DIR / "persona_pool.jsonl"
    if persona_path.exists():
        personas = PersonaGenerator.load_personas(persona_path)
        inserted = mongo.insert_personas(personas)
        logger.info(f"📥 Personas: {inserted} new / {len(personas)} total synced to MongoDB")
    else:
        logger.warning(f"No persona file found at {persona_path}")

    # Sync conversations
    conv_files = sorted(config.CONVERSATIONS_DIR.glob("conversations_*.jsonl"))
    total_convs = 0
    total_inserted = 0
    for f in conv_files:
        conversations = ConversationLogger.load_conversations(f)
        inserted = mongo.insert_conversations(conversations)
        total_convs += len(conversations)
        total_inserted += inserted
        logger.info(f"  📄 {f.name}: {inserted} new / {len(conversations)} total")

    logger.info(f"📥 Conversations: {total_inserted} new / {total_convs} total synced to MongoDB")

    # Print summary
    stats = mongo.get_summary_stats()
    logger.info(f"\n📊 MongoDB totals:")
    logger.info(f"  Personas: {stats['total_personas']}")
    logger.info(f"  Conversations: {stats['total_conversations']}")


def cmd_mongo_stats(args):
    """Print summary statistics from MongoDB."""
    from src.storage.mongo_client import get_mongo_storage

    logger = logging.getLogger("main")
    mongo = get_mongo_storage()
    stats = mongo.get_summary_stats()

    logger.info("\n📊 MONGODB STATISTICS")
    logger.info(f"  Personas: {stats['total_personas']}")
    logger.info(f"  Conversations: {stats['total_conversations']}")
    logger.info(f"  Matches accepted: {stats['matches_accepted']} ({stats['acceptance_rate']:.0%})")
    logger.info(f"  Drop-offs: {stats['dropped_off']}")

    if stats["avg_post_date_rating"]:
        logger.info(f"  Avg post-date rating: {stats['avg_post_date_rating']}/5")
    if stats["avg_rounds_to_acceptance"]:
        logger.info(f"  Avg rounds to acceptance: {stats['avg_rounds_to_acceptance']}")

    if stats["gender_distribution"]:
        logger.info("\n  Gender distribution:")
        for gender, count in stats["gender_distribution"].items():
            logger.info(f"    {gender}: {count}")

    if stats["rating_distribution"]:
        logger.info("\n  Rating distribution:")
        for rating, count in stats["rating_distribution"].items():
            logger.info(f"    ⭐{rating}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description="Ditto Synthetic Matchmaking Feedback Loop Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py generate-personas --count 20 --preview
  python main.py simulate --num-conversations 5
  python main.py simulate --num-conversations 5 --mongo
  python main.py sync-to-mongo
  python main.py mongo-stats
  python main.py validate data/conversations/conversations_*.jsonl
        """,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Generate personas
    gen_parser = subparsers.add_parser(
        "generate-personas",
        help="Generate synthetic dating personas",
    )
    gen_parser.add_argument("--count", type=int, default=20, help="Number of personas (default: 20)")
    gen_parser.add_argument("--batch-size", type=int, default=config.PERSONA_BATCH_SIZE, help="Personas per LLM call")
    gen_parser.add_argument("--output", type=str, default=None, help="Output JSONL path")
    gen_parser.add_argument("--preview", action="store_true", help="Print sample personas")
    gen_parser.add_argument("--mongo", action="store_true", help="Also sync to MongoDB")

    # Run simulation
    sim_parser = subparsers.add_parser(
        "simulate",
        help="Run matchmaking conversation simulation",
    )
    sim_parser.add_argument("--num-conversations", type=int, default=5, help="Number of conversations (default: 5)")
    sim_parser.add_argument("--persona-file", type=str, default=None, help="Path to persona JSONL")
    sim_parser.add_argument("--model", type=str, default=None,
                           help="Ollama model to use (default: from config, llama3.2)")
    sim_parser.add_argument("--mongo", action="store_true", help="Also sync to MongoDB")

    # Validate
    val_parser = subparsers.add_parser(
        "validate",
        help="Validate conversation JSONL logs",
    )
    val_parser.add_argument("file", type=str, help="Path to JSONL file to validate")

    # Sync to MongoDB
    sync_parser = subparsers.add_parser(
        "sync-to-mongo",
        help="Bulk import existing JSONL files into MongoDB",
    )

    # MongoDB stats
    stats_parser = subparsers.add_parser(
        "mongo-stats",
        help="Print summary statistics from MongoDB",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "generate-personas":
        cmd_generate_personas(args)
    elif args.command == "simulate":
        cmd_run_simulation(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "sync-to-mongo":
        cmd_sync_to_mongo(args)
    elif args.command == "mongo-stats":
        cmd_mongo_stats(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

