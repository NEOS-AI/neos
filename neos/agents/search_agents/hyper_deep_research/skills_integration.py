"""Skills Integration Module for HyperDeepResearch.

This module handles integration with external skills/tools:
- ArXiv search for academic papers
- PubMed search for medical literature
- Wikipedia search for background knowledge
- Research assistant skills
"""

from typing import Dict, Any, List, Optional
import asyncio
import logging


logger = logging.getLogger(__name__)


# Domain detection keywords
SCIENCE_ENGINEERING_KEYWORDS = [
    "ai", "ml", "machine learning", "deep learning", "neural network",
    "algorithm", "computer science", "physics", "mathematics", "math",
    "engineering", "quantum", "robotics", "nlp", "computer vision",
    "transformer", "llm", "language model", "artificial intelligence",
    "software", "programming", "data science", "statistics",
    "astronomy", "chemistry", "research", "theory", "model",
    "optimization", "simulation", "computational"
]

MEDICAL_BIO_KEYWORDS = [
    "medical", "medicine", "disease", "drug", "vaccine", "clinical",
    "patient", "treatment", "therapy", "diagnosis", "hospital",
    "biology", "biomedical", "gene", "protein", "cell", "cancer",
    "virus", "bacteria", "immune", "health", "pharmaceutical",
    "symptom", "syndrome", "infection", "epidemic", "pandemic",
    "surgery", "healthcare", "doctor", "nurse", "anatomy",
    "physiology", "pathology", "microbiology", "genetics"
]


class SkillsIntegrator:
    """Handles skills integration for research data collection."""
    
    def __init__(self, skill_manager: Any):
        """Initialize skills integrator.
        
        Args:
            skill_manager: Skill manager instance
        """
        self.skill_manager = skill_manager
        self.skills_enabled = False
        self.selected_skills: List[str] = []
        
        self.stats = {
            "arxiv_searches": 0,
            "arxiv_results": 0,
            "pubmed_searches": 0,
            "pubmed_results": 0,
            "wikipedia_searches": 0,
            "wikipedia_results": 0,
        }
    
    async def initialize_skills(self, selected_skills: List[str]) -> bool:
        """Initialize selected skills.
        
        Args:
            selected_skills: List of skill names to initialize
            
        Returns:
            True if at least one skill was initialized
        """
        if not selected_skills:
            print("[WARNING] No skills selected for initialization")
            self.skills_enabled = False
            return False

        print(f"[INFO] 🎯 Initializing {len(selected_skills)} selected skills...")

        initialized_count = 0
        for skill_name in selected_skills:
            if skill_name in self.skill_manager.registry._skills:
                success = await self.skill_manager.initialize_skill(skill_name)
                if success:
                    print(f"[INFO] ✅ {skill_name} skill initialized")
                    initialized_count += 1
                else:
                    print(f"[WARNING] ❌ {skill_name} skill initialization failed")
            else:
                print(f"[WARNING] ❌ {skill_name} skill not found in registry")

        self.skills_enabled = initialized_count > 0
        self.selected_skills = selected_skills
        print(f"[INFO] 📊 Initialized {initialized_count}/{len(selected_skills)} skills")
        
        return self.skills_enabled
    
    def ensure_required_skills(
        self,
        topic_analysis: Dict[str, Any],
        selected_skills: List[str],
    ) -> List[str]:
        """Ensure domain-specific required skills are included.
        
        Args:
            topic_analysis: Topic analysis result
            selected_skills: Currently selected skills
            
        Returns:
            Updated skills list with required domain-specific skills
        """
        updated_skills = list(selected_skills)

        # Extract topic information
        topic_text = topic_analysis.get("full_analysis", "").lower()
        key_aspects = topic_analysis.get("key_aspects", [])
        combined_text = topic_text + " " + " ".join(
            str(aspect).lower() for aspect in key_aspects
        )

        # Check domain matches
        science_match = any(
            keyword in combined_text for keyword in SCIENCE_ENGINEERING_KEYWORDS
        )
        medical_match = any(
            keyword in combined_text for keyword in MEDICAL_BIO_KEYWORDS
        )

        print("\n[INFO] 🔍 Analyzing topic domain for required skills...")

        if science_match and "arxiv" not in updated_skills:
            updated_skills.append("arxiv")
            print("[INFO] 🎓 Science/Engineering/AI topic detected → Adding ArXiv skill")

        if medical_match and "pubmed" not in updated_skills:
            updated_skills.append("pubmed")
            print("[INFO] 🏥 Medical/Biomedical/Health topic detected → Adding PubMed skill")

        if "wikipedia" not in updated_skills:
            updated_skills.append("wikipedia")
            print("[INFO] 📚 Adding Wikipedia skill for background knowledge")

        # Log domain detection
        if science_match or medical_match:
            detected_domains = []
            if science_match:
                detected_domains.append("Science/Engineering/AI")
            if medical_match:
                detected_domains.append("Medical/Biomedical")
            print(f"[INFO] 🎯 Detected domains: {', '.join(detected_domains)}")
        else:
            print("[INFO] 🌐 General topic detected (no specific domain)")

        return updated_skills
    
    async def collect_data_from_skills(
        self,
        query_variations: List[str],
        topic_analysis: Dict[str, Any],
        language: str,
    ) -> List[Dict[str, Any]]:
        """Collect data using selected research skills.
        
        Args:
            query_variations: List of query variations
            topic_analysis: Topic analysis result
            language: Language code
            
        Returns:
            List of search results from skills
        """
        if not self.skills_enabled or not self.selected_skills:
            print("[INFO] 📭 No skills enabled, skipping skill-based data collection")
            return []

        skill_results = []
        print(f"\n[INFO] 🎯 Collecting data from {len(self.selected_skills)} selected skills...")

        # ArXiv
        if "arxiv" in self.selected_skills:
            print("[INFO] 📚 Searching ArXiv for academic papers...")
            try:
                arxiv_results = await self._search_with_arxiv(query_variations, topic_analysis)
                skill_results.extend(arxiv_results)
                print(f"[INFO] ✅ ArXiv: Found {len(arxiv_results)} papers")
            except Exception as e:
                print(f"[WARNING] ArXiv search failed: {e}")

        # PubMed
        if "pubmed" in self.selected_skills:
            print("[INFO] 🏥 Searching PubMed for medical literature...")
            try:
                pubmed_results = await self._search_with_pubmed(query_variations, topic_analysis)
                skill_results.extend(pubmed_results)
                print(f"[INFO] ✅ PubMed: Found {len(pubmed_results)} papers")
            except Exception as e:
                print(f"[WARNING] PubMed search failed: {e}")

        # Wikipedia
        if "wikipedia" in self.selected_skills:
            print("[INFO] 📖 Searching Wikipedia for background knowledge...")
            try:
                wikipedia_results = await self._search_with_wikipedia(
                    query_variations, topic_analysis, language
                )
                skill_results.extend(wikipedia_results)
                print(f"[INFO] ✅ Wikipedia: Found {len(wikipedia_results)} articles")
            except Exception as e:
                print(f"[WARNING] Wikipedia search failed: {e}")

        print(f"[INFO] 📊 Total skill-based sources collected: {len(skill_results)}")
        return skill_results
    
    async def _search_with_arxiv(
        self,
        queries: List[str],
        topic_analysis: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Search ArXiv for academic papers."""
        results = []
        selected_queries = queries[:5] if len(queries) > 5 else queries

        for query in selected_queries:
            try:
                result = await self.skill_manager.execute_skill(
                    "arxiv",
                    {
                        "action": "search",
                        "query": query,
                        "max_results": 5
                    }
                )

                if result.success:
                    papers = result.data.get("papers", [])
                    for paper in papers:
                        results.append({
                            "title": paper.get("title", ""),
                            "content": paper.get("full_summary", paper.get("summary", "")),
                            "url": paper.get("entry_url", ""),
                            "score": 0.95,
                            "source": "arxiv",
                            "metadata": {
                                "arxiv_id": paper.get("arxiv_id", ""),
                                "authors": paper.get("authors", ""),
                                "published": paper.get("published", ""),
                                "pdf_url": paper.get("pdf_url", "")
                            }
                        })
                    self.stats["arxiv_searches"] += 1
                    self.stats["arxiv_results"] += len(papers)

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(f"ArXiv query '{query}' failed: {e}")
                continue

        return results
    
    async def _search_with_pubmed(
        self,
        queries: List[str],
        topic_analysis: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Search PubMed for medical literature."""
        results = []
        selected_queries = queries[:5] if len(queries) > 5 else queries

        for query in selected_queries:
            try:
                result = await self.skill_manager.execute_skill(
                    "pubmed",
                    {
                        "action": "search",
                        "query": query,
                        "max_results": 5
                    }
                )

                if result.success:
                    papers = result.data.get("papers", [])
                    for paper in papers:
                        results.append({
                            "title": paper.get("title", ""),
                            "content": paper.get("full_summary", paper.get("summary", "")),
                            "url": paper.get("pubmed_url", ""),
                            "score": 0.95,
                            "source": "pubmed",
                            "metadata": {
                                "pmid": paper.get("pmid", ""),
                                "authors": paper.get("authors", ""),
                                "published": paper.get("published", "")
                            }
                        })
                    self.stats["pubmed_searches"] += 1
                    self.stats["pubmed_results"] += len(papers)

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(f"PubMed query '{query}' failed: {e}")
                continue

        return results
    
    async def _search_with_wikipedia(
        self,
        queries: List[str],
        topic_analysis: Dict[str, Any],
        language: str,
    ) -> List[Dict[str, Any]]:
        """Search Wikipedia for background knowledge."""
        results = []
        wiki_lang = "en" if language == "en" else "ko" if language == "ko" else "en"
        selected_queries = queries[:3] if len(queries) > 3 else queries

        for query in selected_queries:
            try:
                result = await self.skill_manager.execute_skill(
                    "wikipedia",
                    {
                        "action": "search",
                        "query": query,
                        "max_results": 2,
                        "lang": wiki_lang
                    }
                )

                if result.success:
                    articles = result.data.get("articles", [])
                    for article in articles:
                        results.append({
                            "title": article.get("title", ""),
                            "content": article.get("full_content", article.get("content", "")),
                            "url": article.get("url", ""),
                            "score": 0.85,
                            "source": "wikipedia",
                            "metadata": {
                                "summary": article.get("summary", ""),
                                "language": wiki_lang
                            }
                        })
                    self.stats["wikipedia_searches"] += 1
                    self.stats["wikipedia_results"] += len(articles)

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(f"Wikipedia query '{query}' failed: {e}")
                continue

        return results
    
    async def analyze_source_with_skill(
        self,
        content: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Analyze source using Research Assistant skill."""
        if not self.skills_enabled:
            return {}

        try:
            result = await self.skill_manager.execute_skill(
                "research_assistant",
                {
                    "action": "analyze_source",
                    "content": content,
                    "options": options or {"extract_key_points": True}
                }
            )

            if result.success:
                return result.data
            else:
                logger.warning(f"Skill analysis failed: {result.error}")
                return {}

        except Exception as e:
            logger.warning(f"Error using skill for source analysis: {e}")
            return {}
    
    async def summarize_with_skill(
        self,
        content: str,
        max_length: int = 500,
    ) -> str:
        """Summarize content using Research Assistant skill."""
        if not self.skills_enabled:
            return ""

        try:
            result = await self.skill_manager.execute_skill(
                "research_assistant",
                {
                    "action": "summarize",
                    "content": content,
                    "options": {"max_length": max_length, "style": "academic"}
                }
            )

            if result.success:
                return result.data.get("summary", "")
            return ""

        except Exception as e:
            logger.warning(f"Error using skill for summarization: {e}")
            return ""
    
    async def extract_references_with_skill(
        self,
        content: str,
    ) -> Dict[str, Any]:
        """Extract references using Research Assistant skill."""
        if not self.skills_enabled:
            return {}

        try:
            result = await self.skill_manager.execute_skill(
                "research_assistant",
                {
                    "action": "extract_references",
                    "content": content
                }
            )

            if result.success:
                return result.data
            return {}

        except Exception as e:
            logger.warning(f"Error using skill for reference extraction: {e}")
            return {}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get skills integration statistics."""
        return self.stats.copy()
