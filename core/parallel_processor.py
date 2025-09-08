"""
Parallel processing functionality extracted from HypernymProcessor
"""

import asyncio
import json
import math
import random
import select
import sys
import termios
import threading
import time
import tty
from datetime import datetime
from typing import List, Dict, Any, Optional

import aiohttp
import aiosqlite
from asyncio_throttle import Throttler
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (Progress, SpinnerColumn, BarColumn, TextColumn, 
                          TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn)
from rich.table import Table

from .models import Sample, HypernymResponse
from .core.concurrency import AdaptiveConcurrencyManager

# DEBUG CONSTANT - SET TO True TO SEE SAMPLE PROCESSING AND CACHE HITS
DEBUG_SAMPLES = False

# UI CONSTANT - SET TO True TO ENABLE RICH LIVE DISPLAY
ENABLE_LIVE_UI = True

async def process_batch_parallel(processor, samples: List[Sample], compression_ratio: float = 0.6,
                                    similarity: float = 0.75, batch_size: int = 5,
                                    cooldown: float = 0.5, batch_cooldown: float = 2.0,
                                    timeout: int = 30, max_retries: int = 3,
                                    use_cache: bool = True, max_workers: int = 4,
                                    analysis_mode: str = "partial",
                                    force_detail_count: Optional[int] = None,
                                    force_single_segment: bool = True,
                                    include_embeddings: bool = False,
                                    filters: Optional[Dict[str, Any]] = None,
                                    max_display_workers: int = 20,
                                    ensemble: Optional[str] = None) -> List[Dict[str, Any]]:
        """Process samples in parallel with beautiful progress display"""
        with open('/tmp/hypernym_debug.log', 'a') as f:
            f.write(f"STARTED: process_batch_parallel called with {len(samples)} samples, mode={analysis_mode}\n")
            if len(samples) == 0:
                f.write("ERROR: No samples provided!\n")
                return []
        console = Console()
        
        # Create adaptive concurrency manager
        concurrency_mgr = AdaptiveConcurrencyManager(processor, max_workers)
        
        # Create progress bars
        overall_progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Overall Progress"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
            expand=False
        )
        
        # Worker progress will show a scrollable window
        worker_progress = Progress(
            TextColumn("[bold cyan]{task.fields[worker_name]:>10}"),
            SpinnerColumn(),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[current_sample]}"),
            console=console,
            expand=False
        )
        
        # Track all worker tasks (even if not visible)
        all_worker_tasks = []
        
        # Get historical data from database for accurate averages
        async def get_historical_stats():
            """Pull historical compression and similarity data from database"""
            historical = {
                'all_compressions': [],
                'all_similarities': [],
                'best_compression': 1.0,
                'best_similarity': 0.0
            }
            
            try:
                async with aiosqlite.connect(processor.db_path) as db:
                    # Get all compression ratios and similarities
                    cursor = await db.execute("""
                        SELECT response_data, compression_ratio 
                        FROM hypernym_responses 
                        WHERE compression_ratio > 0
                    """)
                    rows = await cursor.fetchall()
                    
                    for row in rows:
                        compression_ratio = row[1]
                        response_data = json.loads(row[0])
                        
                        # Track compression
                        if compression_ratio > 0:
                            historical['all_compressions'].append(compression_ratio)
                            if compression_ratio < historical['best_compression']:
                                historical['best_compression'] = compression_ratio
                        
                        # Extract similarity from response
                        try:
                            if 'results' in response_data:
                                segments = response_data['results'].get('response', {}).get('segments', [])
                            else:
                                segments = response_data.get('response', {}).get('segments', [])
                            
                            if segments:
                                similarities = [s.get('semantic_similarity', 0) for s in segments if 'semantic_similarity' in s]
                                if similarities:
                                    avg_sim = sum(similarities) / len(similarities)
                                    historical['all_similarities'].append(avg_sim)
                                    if avg_sim > historical['best_similarity']:
                                        historical['best_similarity'] = avg_sim
                        except:
                            pass
                            
            except Exception as e:
                console.print(f"[yellow]⚠️  Could not load historical data: {e}[/yellow]")
            
            return historical
        
        # Stats tracking
        # Get existing counts from database at startup
        async with aiosqlite.connect(processor.db_path) as db:
            # Count total responses
            async with db.execute("""
                SELECT COUNT(DISTINCT sample_id) 
                FROM hypernym_responses
            """) as cursor:
                row = await cursor.fetchone()
                total_already_processed = row[0] if row else 0
            
            # Count standard mode responses (using proper column)
            async with db.execute("""
                SELECT COUNT(DISTINCT sample_id) 
                FROM hypernym_responses
                WHERE analysis_mode IS NULL 
                   OR analysis_mode = 'partial'
                   OR analysis_mode = 'standard'
            """) as cursor:
                row = await cursor.fetchone()
                existing_standard = row[0] if row else 0
            
            # Count comprehensive mode responses (using proper column)
            async with db.execute("""
                SELECT COUNT(DISTINCT sample_id) 
                FROM hypernym_responses
                WHERE analysis_mode = 'comprehensive'
            """) as cursor:
                row = await cursor.fetchone()
                existing_comprehensive = row[0] if row else 0
            
            # Count content errors (422s)
            async with db.execute("""
                SELECT COUNT(DISTINCT sample_id) 
                FROM content_errors
            """) as cursor:
                row = await cursor.fetchone()
                existing_content_errors = row[0] if row else 0
            
            # Count other errors
            async with db.execute("""
                SELECT COUNT(DISTINCT sample_id) 
                FROM error_entries
                WHERE status_code != 422
            """) as cursor:
                row = await cursor.fetchone()
                existing_other_errors = row[0] if row else 0
        
        historical_data = await get_historical_stats()
        stats = {
            'processed_standard': existing_standard,  # Total in DB
            'processed_comprehensive': existing_comprehensive,  # Total in DB
            'errors': 0,  # This session only
            'content_errors': existing_content_errors,  # Total in DB (permanent)
            'cached': 0,  # Cache hits this session
            'cache_hits': existing_comprehensive if analysis_mode == 'comprehensive' else existing_standard,  # Start with what will be found
            'cache_hits_standard': 0 if analysis_mode == 'comprehensive' else existing_standard,
            'cache_hits_comprehensive': existing_comprehensive if analysis_mode == 'comprehensive' else 0,
            'rate_limited': 0,
            'session_standard': 0,  # This session only for rate calc
            'session_comprehensive': 0,  # This session only for rate calc
            'start_time': time.time(),
            'recent_compressions': [],  # Track last 10 compression ratios
            'recent_similarities': [],  # Track last 10 similarity scores
            'all_compressions': historical_data['all_compressions'],  # ALL historical data
            'all_similarities': historical_data['all_similarities'],  # ALL historical data
            'best_compression': historical_data['best_compression'],
            'best_similarity': historical_data['best_similarity'],
            'animation_frame': 0,
            'scroll_offset': 0,  # For scrolling through workers
            'max_scroll': 0,  # Will be set based on worker count
            'total_in_db': total_already_processed  # Total already processed
        }
        
        # Keyboard input handling
        import sys, tty, termios, select
        import threading
        
        def handle_keyboard():
            """Handle keyboard input for scrolling"""
            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setcbreak(sys.stdin.fileno())
                while True:
                    if select.select([sys.stdin], [], [], 0)[0]:
                        key = sys.stdin.read(1)
                        if key == '\x1b':  # ESC sequence
                            next_chars = sys.stdin.read(2)
                            if next_chars == '[A':  # Up arrow
                                stats['scroll_offset'] = max(0, stats['scroll_offset'] - 1)
                            elif next_chars == '[B':  # Down arrow  
                                stats['scroll_offset'] = min(stats['max_scroll'], stats['scroll_offset'] + 1)
                            elif next_chars == '[5':  # Page up
                                if sys.stdin.read(1) == '~':
                                    stats['scroll_offset'] = max(0, stats['scroll_offset'] - 18)
                            elif next_chars == '[6':  # Page down
                                if sys.stdin.read(1) == '~':
                                    stats['scroll_offset'] = min(stats['max_scroll'], stats['scroll_offset'] + 18)
                    time.sleep(0.05)
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        
        # Start keyboard thread
        keyboard_thread = threading.Thread(target=handle_keyboard, daemon=True)
        keyboard_thread.start()
        
        # Results storage
        results = {}
        
        def create_average_banners():
            """Create Megaman-style banners showing averages"""
            # Calculate averages from historical data
            avg_compression = sum(stats['all_compressions']) / len(stats['all_compressions']) if stats['all_compressions'] else 0.0
            avg_similarity = sum(stats['all_similarities']) / len(stats['all_similarities']) if stats['all_similarities'] else 0.0
            
            banner_lines = []
            
            # Compression banner
            comp_percent = (1 - avg_compression) * 100
            comp_bar = "█" * int(comp_percent / 5)  # 20 blocks max
            banner_lines.append(f"[bold yellow]╔═══════════════════════════╗[/bold yellow]")
            banner_lines.append(f"[bold yellow]║[/bold yellow] [bold red]⚡ COMPRESSION POWER ⚡[/bold red]   [bold yellow]║[/bold yellow]")
            banner_lines.append(f"[bold yellow]╠═══════════════════════════╣[/bold yellow]")
            banner_lines.append(f"[bold yellow]║[/bold yellow] [{comp_bar:<23}] [bold yellow]║[/bold yellow]")
            banner_lines.append(f"[bold yellow]║[/bold yellow]           [bold white]{comp_percent:>5.1f}%[/bold white]          [bold yellow]║[/bold yellow]")
            banner_lines.append(f"[bold yellow]╚═══════════════════════════╝[/bold yellow]")
            
            banner_lines.append("")  # Spacer
            
            # Similarity banner
            sim_percent = avg_similarity * 100
            sim_bar = "█" * int(sim_percent / 5)  # 20 blocks max
            banner_lines.append(f"[bold cyan]╔═══════════════════════════╗[/bold cyan]")
            banner_lines.append(f"[bold cyan]║[/bold cyan] [bold blue]💎 SIMILARITY SHIELD 💎[/bold blue]   [bold cyan]║[/bold cyan]")
            banner_lines.append(f"[bold cyan]╠═══════════════════════════╣[/bold cyan]")
            banner_lines.append(f"[bold cyan]║[/bold cyan] [{sim_bar:<23}] [bold cyan]║[/bold cyan]")
            banner_lines.append(f"[bold cyan]║[/bold cyan]           [bold white]{sim_percent:>5.1f}%[/bold white]          [bold cyan]║[/bold cyan]")
            banner_lines.append(f"[bold cyan]╚═══════════════════════════╝[/bold cyan]")
            
            banner_lines.append("")  # Spacer
            
            # Sample count
            banner_lines.append(f"[dim]Historical samples: {len(stats['all_compressions']):,}[/dim]")
            
            # Combo meter
            if comp_percent > 70 and sim_percent > 85:
                banner_lines.append("")
                banner_lines.append("[bold red on yellow blink]★ MEGA COMBO ACTIVE ★[/bold red on yellow blink]")
            
            return "\n".join(banner_lines)
        
        def create_best_scores_display():
            """Create display with 1D violin plots using exact style requested"""
            lines = []
            
            # Calculate statistics for all samples
            if stats['all_compressions']:
                comp_values = [(1-x)*100 for x in stats['all_compressions']]  # Convert to percentage
                comp_min = min(comp_values)
                comp_max = max(comp_values)
                comp_avg = sum(comp_values) / len(comp_values)
                comp_q1 = sorted(comp_values)[len(comp_values)//4]
                comp_q3 = sorted(comp_values)[3*len(comp_values)//4]
                
                # Calculate standard deviation
                comp_std = (sum((x - comp_avg) ** 2 for x in comp_values) / len(comp_values)) ** 0.5
                
                # Create violin plot for compression: ||---===|~~~~|===---||
                lines.append("[bold red]🏆 COMPRESSION[/bold red]")
                lines.append(f"Best: [bold yellow]{comp_max:.1f}%[/bold yellow]  Avg: {comp_avg:.1f}%")
                
                # Build violin plot: ||---------======|~~~~|==-----||
                graph_width = 40
                
                # Calculate standard error for error bars
                comp_se = comp_std / (len(comp_values) ** 0.5)
                
                # Map values to positions on the graph
                min_pos = int(comp_min / 100 * graph_width)
                max_pos = int(comp_max / 100 * graph_width)
                q1_pos = int(comp_q1 / 100 * graph_width)
                q3_pos = int(comp_q3 / 100 * graph_width)
                avg_pos = int(comp_avg / 100 * graph_width)
                error_left = int((comp_avg - comp_se) / 100 * graph_width)
                error_right = int((comp_avg + comp_se) / 100 * graph_width)
                
                # Build the violin character by character
                violin = ""
                i = 0
                while i < graph_width:
                    if i == min_pos:
                        violin += "||"
                        i += 2
                    elif i == max_pos and max_pos != min_pos + 1:
                        violin += "||"
                        i += 2
                    elif i == error_left:
                        violin += "|"
                        i += 1
                    elif i == error_right:
                        violin += "|"
                        i += 1
                    elif i > error_left and i < error_right:
                        violin += "~"
                        i += 1
                    elif i >= q1_pos and i <= q3_pos:
                        violin += "="
                        i += 1
                    elif i > min_pos and i < q1_pos:
                        violin += "-"
                        i += 1
                    elif i > q3_pos and i < max_pos:
                        violin += "-"
                        i += 1
                    else:
                        violin += " "
                        i += 1
                
                lines.append(violin)
                lines.append(f"0%{' ' * 18}50%{' ' * 17}100%")
                lines.append("")
            
            # Similar for similarity scores
            if stats['all_similarities']:
                sim_values = [x*100 for x in stats['all_similarities']]
                sim_min = min(sim_values)
                sim_max = max(sim_values)
                sim_avg = sum(sim_values) / len(sim_values)
                sim_q1 = sorted(sim_values)[len(sim_values)//4]
                sim_q3 = sorted(sim_values)[3*len(sim_values)//4]
                
                # Calculate standard deviation
                sim_std = (sum((x - sim_avg) ** 2 for x in sim_values) / len(sim_values)) ** 0.5
                
                lines.append("[bold cyan]🏆 SIMILARITY[/bold cyan]")
                lines.append(f"Best: [bold green]{sim_max:.1f}%[/bold green]  Avg: {sim_avg:.1f}%")
                
                # Build violin plot: ||---------======|~~~~|==-----||
                graph_width = 40
                
                # Calculate standard error for error bars
                sim_se = sim_std / (len(sim_values) ** 0.5)
                
                # Map values to positions on the graph
                min_pos = int(sim_min / 100 * graph_width)
                max_pos = int(sim_max / 100 * graph_width)
                q1_pos = int(sim_q1 / 100 * graph_width)
                q3_pos = int(sim_q3 / 100 * graph_width)
                avg_pos = int(sim_avg / 100 * graph_width)
                error_left = int((sim_avg - sim_se) / 100 * graph_width)
                error_right = int((sim_avg + sim_se) / 100 * graph_width)
                
                # Build the violin character by character
                violin = ""
                i = 0
                while i < graph_width:
                    if i == min_pos:
                        violin += "||"
                        i += 2
                    elif i == max_pos and max_pos != min_pos + 1:
                        violin += "||"
                        i += 2
                    elif i == error_left:
                        violin += "|"
                        i += 1
                    elif i == error_right:
                        violin += "|"
                        i += 1
                    elif i > error_left and i < error_right:
                        violin += "~"
                        i += 1
                    elif i >= q1_pos and i <= q3_pos:
                        violin += "="
                        i += 1
                    elif i > min_pos and i < q1_pos:
                        violin += "-"
                        i += 1
                    elif i > q3_pos and i < max_pos:
                        violin += "-"
                        i += 1
                    else:
                        violin += " "
                        i += 1
                
                lines.append(violin)
                lines.append(f"0%{' ' * 18}50%{' ' * 17}100%")
                lines.append("")
            
            lines.append(f"[dim]Total samples: {len(stats['all_compressions']):,}[/dim]")
            
            return "\n".join(lines)
        
        def create_pinball_animation():
            """Create display with two ASCII graphs"""
            # Get last 50 samples for graphs
            recent_comp = stats['all_compressions'][-50:] if len(stats['all_compressions']) > 50 else stats['all_compressions']
            recent_sim = stats['all_similarities'][-50:] if len(stats['all_similarities']) > 50 else stats['all_similarities']
            
            # Build display
            display = []
            display.append("╔" + "═" * 95 + "╗")
            display.append("║" + " " * 32 + "🎮 HYPERNYM PERFORMANCE 🎮" + " " * 33 + "║")
            display.append("╠" + "═" * 95 + "╣")
            display.append("║" + " " * 95 + "║")
            
            # Best scores boxes
            display.append("║ ┌─────────────────────────┐" + " " * 41 + "┌─────────────────────────┐ ║")
            display.append(f"║ │ 🏆 BEST COMPRESSION: {(1-stats['best_compression'])*100:>3.0f}% │" + " " * 41 + f"│ 🏆 BEST SIMILARITY: {stats['best_similarity']*100:>3.0f}% │ ║")
            display.append("║ └─────────────────────────┘" + " " * 41 + "└─────────────────────────┘ ║")
            display.append("║" + " " * 95 + "║")
            
            # Graph headers
            display.append("║ Compression History (last 50 samples)" + " " * 18 + "Similarity History (last 50 samples)   ║")
            
            # Create ASCII graphs
            if recent_comp and recent_sim:
                # Calculate ranges
                comp_values = [(1-x)*100 for x in recent_comp]  # Convert to percentage
                sim_values = [x*100 for x in recent_sim]
                
                # Create line graph for compression
                comp_graph = []
                for y in range(100, 40, -10):  # 100% to 50% 
                    line = f"{y:>3}%┤"
                    for i, val in enumerate(comp_values[-30:]):  # Last 30 points
                        if i == 0:
                            line += " "
                        elif abs(val - y) < 5:
                            line += "═"
                        elif comp_values[i-1] < y < val or val < y < comp_values[i-1]:
                            line += "╱" if val > comp_values[i-1] else "╲"
                        else:
                            line += " "
                    comp_graph.append(line)
                
                # Create bar graph for similarity
                sim_graph = []
                sim_avg = sum(sim_values) / len(sim_values)
                sim_min = min(sim_values)
                sim_max = max(sim_values)
                
                for y in range(100, 40, -10):
                    line = f"{y:>3}%┤"
                    if sim_min <= y <= sim_max:
                        if abs(y - sim_avg) < 5:
                            line += "═" * 30
                        else:
                            line += "║" + " " * 28 + "║"
                    else:
                        line += " " * 30
                    sim_graph.append(line)
                
                # Display graphs side by side
                for i in range(len(comp_graph)):
                    display.append(f"║ {comp_graph[i]:<44} {sim_graph[i]:<45} ║")
                
                # Graph bottom line
                display.append("║    └" + "─" * 30 + " " * 14 + "└" + "─" * 30 + " ║")
                
                # Stats
                comp_avg = sum(comp_values) / len(comp_values)
                sim_avg = sum(sim_values) / len(sim_values)
                display.append(f"║    [Min: {min(comp_values):>2.0f}%  Avg: {comp_avg:>2.0f}%  Max: {max(comp_values):>2.0f}%]" + 
                             " " * 19 + 
                             f"[Min: {min(sim_values):>2.0f}%  Avg: {sim_avg:>2.0f}%  Max: {max(sim_values):>2.0f}%]   ║")
            else:
                # No data message
                for _ in range(8):
                    display.append("║" + " " * 95 + "║")
                display.append("║" + " " * 40 + "[No data yet]" + " " * 42 + "║")
            
            display.append("╚" + "═" * 95 + "╝")
            
            return "\n".join(display)
        
        def make_stats_table():
            """Create stats table"""
            table = Table(show_header=False, box=None, padding=(0, 2))
            
            elapsed = time.time() - stats['start_time']
            session_processed = stats['session_standard'] + stats['session_comprehensive']
            rate = session_processed / elapsed if elapsed > 0 else 0
            
            # Show total in DB
            table.add_row("[bold white]📊 Total in DB", f"[bold white]{stats['total_in_db']:,}")
            table.add_row("[green]✓ Standard", f"[bold green]{stats['processed_standard']:,}")
            table.add_row("[blue]✓ Comprehensive", f"[bold blue]{stats['processed_comprehensive']:,}")
            table.add_row("[yellow]⚡ Cache Hits", f"[bold yellow]{stats['cache_hits']:,}")
            table.add_row("[red]🚫 Content Errors (422)", f"[bold red]{stats['content_errors']:,}")
            table.add_row("[orange1]⚠️  Other Errors", f"[bold orange1]{stats['errors']:,}")
            table.add_row("[magenta]⏱ Rate Limited", f"[bold magenta]{stats['rate_limited']:,}")
            table.add_row("[blue]⚡ Rate", f"[bold blue]{rate:.1f}/sec")
            table.add_row("[cyan]👷 Workers", f"[bold cyan]{concurrency_mgr.current_workers}/{concurrency_mgr.max_workers}")
            
            return table
        
        def make_layout(num_workers, max_display_workers=20):
            """Create the layout"""
            layout = Layout()
            
            # Calculate optimal progress panel size based on max_display_workers
            # Account for comprehensive mode workers needing 3 lines each
            comprehensive_count = sum(1 for w in all_worker_tasks if w.get('mode') == 'comprehensive' and w.get('visible', False))
            standard_count = min(num_workers, max_display_workers) - comprehensive_count
            
            # Each comprehensive worker needs 3 lines, standard needs 1
            display_lines_needed = standard_count + (comprehensive_count * 3)
            worker_panel_size = min(max(display_lines_needed, 10), max_display_workers * 2)
            progress_panel_size = worker_panel_size + 3  # +3 for overall progress bar
            
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="progress", size=progress_panel_size),
                Layout(name="bottom")
            )
            
            # Split bottom section into stats and best scores
            layout["bottom"].split_row(
                Layout(name="stats", ratio=1),
                Layout(name="best_scores", ratio=1)
            )
            
            layout["header"].update(
                Panel(
                    Align.center(
                        f"[bold][rgb(164,27,27)]H[/rgb(164,27,27)][rgb(247,185,121)]Y[/rgb(247,185,121)][rgb(196,153,21)]P[/rgb(196,153,21)][rgb(68,126,42)]E[/rgb(68,126,42)][rgb(85,140,152)]R[/rgb(85,140,152)][rgb(81,135,220)]N[/rgb(81,135,220)][rgb(167,202,234)]Y[/rgb(167,202,234)][rgb(59,46,98)]M[/rgb(59,46,98)] Parallel Processor[/bold]\n"
                        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
                        vertical="middle"
                    ),
                    border_style="blue"
                )
            )
            
            
            # Create progress panels layout
            progress_left = Layout()
            
            # Calculate visible range based on scroll offset
            visible_start = stats.get('scroll_offset', 0)
            visible_end = min(visible_start + max_display_workers, num_workers)
            
            # Create scrolling indicator
            if num_workers > max_display_workers:
                # Calculate position for iOS-style scrollbar
                scroll_percent = visible_start / max(1, num_workers - max_display_workers)
                position_text = f"[{visible_start+1}-{visible_end}/{num_workers}]"
                
                # Add scroll indicators
                scroll_info = "↑/↓: scroll 1 | PgUp/PgDn: scroll 18"
                
                worker_panel_content = Panel(
                    worker_progress, 
                    border_style="cyan",
                    title=f"[bold cyan]Workers {position_text}[/bold cyan]",
                    subtitle=f"[dim]{scroll_info}[/dim]"
                )
            else:
                worker_panel_content = Panel(worker_progress, border_style="cyan")
            
            progress_left.split_column(
                Layout(Panel(overall_progress, border_style="green"), size=3),
                Layout(worker_panel_content)
            )
            
            # Split progress into left (bars) and right (banners)
            progress_content = Layout()
            progress_content.split_row(
                Layout(progress_left, ratio=3),
                Layout(
                    Panel(
                        Align.center(create_average_banners(), vertical="middle"),
                        title="[bold magenta]📊 Performance Meters 📊[/bold magenta]",
                        border_style="magenta"
                    ),
                    ratio=1
                )
            )
            layout["progress"].update(progress_content)
            
            layout["stats"].update(
                Panel(
                    Align.center(make_stats_table(), vertical="middle"),
                    title="[bold]Statistics[/bold]",
                    border_style="yellow"
                )
            )
            
            layout["best_scores"].update(
                Panel(
                    Align.center(create_best_scores_display(), vertical="middle"),
                    title="[bold]🏆 High Scores 🏆[/bold]",
                    border_style="green"
                )
            )
            
            return layout
        
        async def poll_comprehensive_status(processor, session, sample, request_id, worker_info, 
                                          stats, concurrency_mgr, worker_progress, request_hash,
                                          start_time, compression_ratio, similarity):
            """Poll /analyze_status for comprehensive mode progress"""
            with open('/tmp/hypernym_debug.log', 'a') as f:
                f.write(f"POLLING: Started polling for sample {sample.id}, request_id={request_id}\n")
            poll_count = 0
            max_polls = 240  # 20 minutes max (240 * 5 seconds)
            poll_interval = 5  # Seconds between polls
            
            while poll_count < max_polls:
                await asyncio.sleep(poll_interval)  # Poll every 5 seconds
                poll_count += 1
                
                try:
                    async with session.get(
                        f"{processor.api_url.replace('/analyze_sync', '/analyze_status')}/{request_id}",
                        headers={'X-API-Key': processor.api_key},
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        with open('/tmp/hypernym_debug.log', 'a') as f:
                            f.write(f"POLL: Sample {sample.id} poll #{poll_count} - status code {response.status}\n")
                        if response.status != 200:
                            # ALWAYS LOG THE ACTUAL RESPONSE FIRST
                            try:
                                response_text = await response.text()
                                with open('/tmp/hypernym_debug.log', 'a') as f:
                                    f.write(f"POLL ERROR: Sample {sample.id} got status {response.status}\n")
                                    f.write(f"Response body: {response_text}\n")
                                    f.write(f"Response headers: {dict(response.headers)}\n")
                            except:
                                response_text = "Could not read response body"
                            
                            # Handle specific status codes
                            if response.status == 404:
                                raise Exception(f"Request {request_id} not found")
                            elif response.status == 422:
                                # Content error - parse the error details
                                try:
                                    error_data = json.loads(response_text) if response_text else {}
                                except:
                                    error_data = {}
                                error_msg = error_data.get('error', 'Content rejected')
                                
                                # Save as content error
                                stats['content_errors'] += 1
                                processor._save_content_error(
                                    sample.id,
                                    f"Content rejected (422): {error_msg}",
                                    request_params={
                                        'min_compression_ratio': compression_ratio,
                                        'min_semantic_similarity': similarity,
                                        'analysis_mode': 'comprehensive'
                                    },
                                    content_length=len(sample.content) if hasattr(sample, 'content') else 0
                                )
                                
                                # Return error result
                                return {
                                    'success': False,
                                    'sample_id': sample.id,
                                    'error': error_msg,
                                    'status_code': 422,
                                    'permanent_failure': True
                                }
                            elif response.status == 500:
                                # Server error - might be temporary, continue polling
                                with open('/tmp/hypernym_debug.log', 'a') as f:
                                    f.write(f"POLL: 500 error, will continue polling (attempt {poll_count}/{max_polls})\n")
                                await asyncio.sleep(poll_interval)
                                continue
                            elif response.status == 503:
                                # Service unavailable - temporary, continue polling
                                with open('/tmp/hypernym_debug.log', 'a') as f:
                                    f.write(f"POLL: 503 service unavailable, will continue polling\n")
                                await asyncio.sleep(poll_interval)
                                continue
                            else:
                                # Unknown error - log and raise
                                raise Exception(f"Unexpected status {response.status}: {response_text}")
                        
                        status_data = await response.json()
                        status = status_data.get("metadata", {}).get("status", "unknown")
                        with open('/tmp/hypernym_debug.log', 'a') as f:
                            f.write(f"POLL: Sample {sample.id} status = {status}\n")
                            # ALWAYS log the full response
                            import json as json_module
                            f.write(f"FULL RESPONSE: {json_module.dumps(status_data)}\n")
                        
                        # Check if still processing
                        if status_data.get("metadata", {}).get("status") == "processing":
                            progress = status_data.get("metadata", {}).get("progress", {})
                            
                            # Update worker info with progress
                            if worker_info:
                                # Format ETA
                                time_estimates = progress.get('time_estimates') or {}
                                eta_seconds = time_estimates.get('estimated_remaining_seconds', 0) or 0
                                if eta_seconds and eta_seconds > 0:
                                    eta_string = f"{int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
                                else:
                                    eta_string = "calculating..."
                                
                                worker_info['progress'] = {
                                    'percent_complete': progress.get('percent_complete', 0),
                                    'current_status': progress.get('current_status', 'Processing...'),
                                    'total_paragraphs': progress.get('total_paragraphs', 0),
                                    'completed_paragraphs': progress.get('completed_paragraphs', 0),
                                    'eta_string': eta_string
                                }
                                
                                # Extract current trial info from paragraph_trials
                                paragraph_trials = progress.get('paragraph_trials', {})
                                for para_idx, para_info in paragraph_trials.items():
                                    if para_info.get('status') == 'processing':
                                        worker_info['progress']['current_trial'] = para_info.get('completed_trials', 0)
                                        worker_info['progress']['total_trials'] = para_info.get('total_trials', 60)
                                        break
                                
                                # Update display
                                if worker_info['visible'] and worker_info['task_id'] is not None:
                                    # Build progress string
                                    prog = worker_info['progress']
                                    progress_lines = []
                                    
                                    # Main sample line
                                    main_line = f"Sample #{sample.id:04d} [blue]COMP[/blue]"
                                    
                                    # Progress detail line
                                    if prog.get('current_status'):
                                        progress_lines.append(f"\n↳ {prog['current_status']}")
                                    
                                    # ETA line
                                    if prog.get('eta_string'):
                                        progress_lines.append(f"\n↳ ETA: {prog['eta_string']} remaining")
                                    
                                    # Update worker display
                                    worker_progress.update(
                                        worker_info['task_id'],
                                        current_sample=main_line + "".join(progress_lines)
                                    )
                        
                        # Check if completed (including "unknown" which appears to be completed)
                        elif status_data.get("metadata", {}).get("status") in ["completed", "unknown"]:
                            with open('/tmp/hypernym_debug.log', 'a') as f:
                                f.write(f"COMPLETED: Comprehensive response received for sample {sample.id}, status={status_data.get('metadata', {}).get('status')}\n")
                                if status_data.get('metadata', {}).get('status') == 'unknown':
                                    import json as json_module
                                    f.write(f"UNKNOWN DATA: {json_module.dumps(status_data)[:1000]}\n")
                            # Extract the actual response
                            if "response" in status_data:
                                # Processing complete!
                                processing_time = time.time() - start_time
                                # Construct proper response with request params
                                result = {
                                    'response': status_data.get('response', {}),
                                    'metadata': status_data.get('metadata', {}),
                                    'request': {
                                        'content': sample.content,
                                        'params': {
                                            'analysis_mode': 'comprehensive',
                                            'min_compression_ratio': compression_ratio,
                                            'min_semantic_similarity': similarity
                                        }
                                    }
                                }
                                
                                # Extract compression ratio and similarity
                                segments = result.get('response', {}).get('segments', [])
                                if segments:
                                    segment_ratios = [s.get('compression_ratio', 0) for s in segments]
                                    actual_ratio = sum(segment_ratios) / len(segment_ratios) if segment_ratios else 0.0
                                    
                                    similarities = [s.get('semantic_similarity', 0.75) for s in segments if 'semantic_similarity' in s]
                                    avg_similarity = sum(similarities) / len(similarities) if similarities else 0.75
                                else:
                                    actual_ratio = 0.0
                                    avg_similarity = 0.75
                                
                                # Stats already updated elsewhere
                                stats['session_comprehensive'] += 1
                                concurrency_mgr.record_success(processing_time)
                                
                                # Track metrics
                                stats['recent_compressions'].append(actual_ratio)
                                stats['recent_similarities'].append(avg_similarity)
                                stats['all_compressions'].append(actual_ratio)
                                stats['all_similarities'].append(avg_similarity)
                                
                                # Update high scores
                                if actual_ratio < stats['best_compression']:
                                    stats['best_compression'] = actual_ratio
                                if avg_similarity > stats['best_similarity']:
                                    stats['best_similarity'] = avg_similarity
                                
                                # Save to cache
                                try:
                                    with open('/tmp/hypernym_debug.log', 'a') as f:
                                        f.write(f"SAVING: Comprehensive response for sample {sample.id}\n")
                                    processor._save_response(sample.id, request_hash, result, actual_ratio, processing_time)
                                    # Debug: verify save happened
                                    import sqlite3
                                    with sqlite3.connect(processor.db_path) as conn:
                                        cursor = conn.execute(
                                            "SELECT COUNT(*) FROM hypernym_responses WHERE sample_id = ? AND analysis_mode = 'comprehensive'",
                                            (sample.id,)
                                        )
                                        count = cursor.fetchone()[0]
                                        if count == 0:
                                            raise Exception(f"Save failed for sample {sample.id} - not found in database after save!")
                                except Exception as save_error:
                                    # Log but don't raise - let processing continue
                                    with open('/tmp/hypernym_debug.log', 'a') as f:
                                        f.write(f"ERROR: Failed to save comprehensive response for sample {sample.id}: {save_error}\n")
                                
                                # Update display to show completion
                                if worker_info:
                                    worker_info['current_sample'] = f"Sample #{sample.id:04d} [green](done)[/green] [blue]COMP[/blue]"
                                    if worker_info['visible'] and worker_info['task_id'] is not None:
                                        worker_progress.update(
                                            worker_info['task_id'],
                                            current_sample=worker_info['current_sample']
                                        )
                                
                                return {
                                    'success': True,
                                    'sample_id': sample.id,
                                    'compression_ratio': actual_ratio,
                                    'processing_time': processing_time,
                                    'cached': False,
                                    'response': result
                                }
                            else:
                                raise Exception("Completed but no response data")
                        
                        # Check for errors
                        elif status_data.get("metadata", {}).get("status") == "failed":
                            error_msg = status_data.get("metadata", {}).get("error", "Unknown error")
                            # Save error and return failure (don't throw exception)
                            processor._save_error(
                                sample.id,
                                'Exception',
                                f"Analysis failed: {error_msg}",
                                status_code=None,
                                request_params={
                                    'min_compression_ratio': compression_ratio,
                                    'min_semantic_similarity': similarity,
                                    'analysis_mode': 'comprehensive'
                                },
                                content_length=len(sample.content) if hasattr(sample, 'content') else 0
                            )
                            return {
                                'success': False,
                                'sample_id': sample.id,
                                'error': error_msg,
                                'permanent_failure': False
                            }
                        elif "error" in status_data:
                            error_msg = str(status_data['error'])
                            # Save error and return failure
                            processor._save_error(
                                sample.id,
                                'Exception',
                                f"Analysis failed: {error_msg}",
                                status_code=None,
                                request_params={
                                    'min_compression_ratio': compression_ratio,
                                    'min_semantic_similarity': similarity,
                                    'analysis_mode': 'comprehensive'
                                },
                                content_length=len(sample.content) if hasattr(sample, 'content') else 0
                            )
                            return {
                                'success': False,
                                'sample_id': sample.id,
                                'error': error_msg,
                                'permanent_failure': False
                            }
                        
                        # Check if we have a complete response even without explicit status
                        elif status_data.get("response") and status_data.get("metadata") and status_data.get("metadata", {}).get("status") != "unknown":
                            # This is a completed response, just missing the status field
                            # Extract the result
                            result = {
                                'response': status_data.get('response', {}),
                                'metadata': status_data.get('metadata', {}),
                                'request': status_data.get('request', {})
                            }
                            
                            # Calculate metrics
                            actual_ratio = 1.0
                            avg_similarity = 1.0
                            
                            # Try to get actual metrics from response
                            if 'segments' in result['response']:
                                segments = result['response']['segments']
                                if segments:
                                    ratios = [s.get('compression_ratio', 1.0) for s in segments]
                                    similarities = [s.get('semantic_similarity', 1.0) for s in segments]
                                    actual_ratio = sum(ratios) / len(ratios) if ratios else 1.0
                                    avg_similarity = sum(similarities) / len(similarities) if similarities else 1.0
                            
                            processing_time = result['metadata'].get('processing_time', 0.0)
                            
                            # Track metrics
                            stats['recent_compressions'].append(actual_ratio)
                            stats['recent_similarities'].append(avg_similarity)
                            stats['all_compressions'].append(actual_ratio)
                            stats['all_similarities'].append(avg_similarity)
                            
                            # Update high scores
                            if actual_ratio < stats['best_compression']:
                                stats['best_compression'] = actual_ratio
                            if avg_similarity > stats['best_similarity']:
                                stats['best_similarity'] = avg_similarity
                            
                            # Save to cache
                            processor._save_response(sample.id, request_hash, result, actual_ratio, processing_time)
                            
                            # Update display to show completion
                            if worker_info:
                                worker_info['current_sample'] = f"Sample #{sample.id:04d} [green](done)[/green] [blue]COMP[/blue]"
                                if worker_info['visible'] and worker_info['task_id'] is not None:
                                    worker_progress.update(
                                        worker_info['task_id'],
                                        current_sample=worker_info['current_sample']
                                    )
                            
                            return {
                                'success': True,
                                'sample_id': sample.id,
                                'compression_ratio': actual_ratio,
                                'processing_time': processing_time,
                                'cached': False,
                                'response': result
                            }
                        
                        # Unknown status with no response data
                        else:
                            status = status_data.get("metadata", {}).get("status", "unknown")
                            raise Exception(f"Unknown status '{status}': {json.dumps(status_data, indent=2)}")
                            
                except asyncio.TimeoutError:
                    # Polling timeout, continue
                    continue
                except Exception as e:
                    # Log error and re-raise
                    if worker_info:
                        worker_info['current_sample'] = f"Sample #{sample.id:04d} [red](poll error)[/red]"
                        if worker_info['visible'] and worker_info['task_id'] is not None:
                            worker_progress.update(
                                worker_info['task_id'],
                                current_sample=worker_info['current_sample']
                            )
                    raise
            
            # Timeout after max polls
            raise Exception(f"Comprehensive analysis timed out after {max_polls * 5} seconds")
        
        async def process_sample_async(processor, session, sample, worker_id, worker_task):
            """Process a single sample asynchronously"""
            # Find worker info
            worker_info = None
            for info in all_worker_tasks:
                if info['id'] == worker_id:
                    worker_info = info
                    break
            
            # Update display if visible
            if worker_info:
                mode_indicator = " [blue]COMP[/blue]" if analysis_mode == 'comprehensive' else " [green]STD[/green]"
                worker_info['current_sample'] = f"Sample #{sample.id:04d}{mode_indicator}"
                if worker_info['visible'] and worker_info['task_id'] is not None:
                    worker_progress.update(
                        worker_info['task_id'],
                        current_sample=worker_info['current_sample']
                    )
            
            # Generate request hash for caching
            request_hash = processor._get_request_hash(
                sample.content, compression_ratio, similarity,
                analysis_mode, force_detail_count, force_single_segment, filters
            )
            
            # NO CACHE CHECK HERE - already done before queue
            if DEBUG_SAMPLES:
                print(f">>> PROCESSING SAMPLE {sample.id} (cache already checked)")
            
            # Make API request
            try:
                headers = {
                    'X-API-Key': processor.api_key,
                    'Content-Type': 'application/json'
                }
                
                params = {
                    'min_compression_ratio': compression_ratio,
                    'min_semantic_similarity': similarity,
                    'analysis_mode': analysis_mode  # CRITICAL: Must include analysis mode!
                }
                if force_detail_count is not None:
                    params['force_detail_count'] = force_detail_count
                if force_single_segment:
                    params['force_single_segment'] = force_single_segment
                if timeout != 60:
                    params['timeout'] = timeout
                if include_embeddings:
                    params['include_embeddings'] = include_embeddings
                if ensemble and processor.has_northstar_access():
                    params['ensemble'] = ensemble
                
                payload = {
                    'essay_text': sample.content,
                    'params': params
                }
                
                if filters:
                    payload['filters'] = filters
                
                with open('/tmp/hypernym_debug.log', 'a') as f:
                    import json
                    f.write(f"PAYLOAD for sample {sample.id}: params={json.dumps(params)}\n")
                
                start_time = time.time()
                
                # For comprehensive mode, use async API
                if analysis_mode == 'comprehensive':
                    with open('/tmp/hypernym_debug.log', 'a') as f:
                        f.write(f"COMPREHENSIVE: Starting async analysis for sample {sample.id}\n")
                    # Start async analysis
                    async with session.post(
                        processor.api_url.replace('/analyze_sync', '/analyze_begin'),
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)  # Short timeout for start
                    ) as response:
                        with open('/tmp/hypernym_debug.log', 'a') as f:
                            f.write(f"COMPREHENSIVE: Got response status {response.status} for sample {sample.id}\n")
                        if response.status == 202:  # Accepted
                            start_data = await response.json()
                            request_id = start_data['metadata']['request_id']
                            with open('/tmp/hypernym_debug.log', 'a') as f:
                                f.write(f"COMPREHENSIVE: Got request_id {request_id} for sample {sample.id}\n")
                            
                            # Store comprehensive mode info
                            if worker_info:
                                worker_info['mode'] = 'comprehensive'
                                worker_info['request_id'] = request_id
                                worker_info['progress'] = {
                                    'percent_complete': 0,
                                    'current_status': 'Starting analysis...',
                                    'eta_string': 'calculating...'
                                }
                                # Initial display
                                worker_info['current_sample'] = f"Sample #{sample.id:04d} [blue]COMP[/blue]\n↳ Starting analysis...\n↳ ETA: calculating..."
                                if worker_info['visible'] and worker_info['task_id'] is not None:
                                    worker_progress.update(
                                        worker_info['task_id'],
                                        current_sample=worker_info['current_sample']
                                    )
                            
                            # Poll for results
                            return await poll_comprehensive_status(
                                processor, session, sample, request_id, worker_info, 
                                stats, concurrency_mgr, worker_progress, request_hash,
                                start_time, compression_ratio, similarity
                            )
                        else:
                            # Log the unexpected response before failing
                            try:
                                response_text = await response.text()
                                with open('/tmp/hypernym_debug.log', 'a') as f:
                                    f.write(f"UNEXPECTED STATUS on analyze_begin: {response.status}\n")
                                    f.write(f"Response: {response_text}\n")
                            except:
                                response_text = "Could not read response"
                            raise Exception(f"Expected 202 from analyze_begin, got {response.status}: {response_text}")
                
                # Standard mode - use sync endpoint
                async with session.post(
                    processor.api_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status == 429:
                        stats['rate_limited'] += 1
                        concurrency_mgr.record_rate_limit()
                        if worker_info:
                            worker_info['current_sample'] = f"Sample #{sample.id:04d} [magenta](rate limited)[/magenta]"
                            if worker_info['visible'] and worker_info['task_id'] is not None:
                                worker_progress.update(
                                    worker_info['task_id'],
                                    current_sample=worker_info['current_sample']
                                )
                        # Exponential backoff with jitter
                        backoff = min(60, 2 ** stats.get('rate_limit_retries', 0) + random.random())
                        await asyncio.sleep(backoff)
                        stats['rate_limit_retries'] = stats.get('rate_limit_retries', 0) + 1
                        raise Exception("Rate limited")
                    
                    # Log any non-200 response before handling
                    if response.status != 200:
                        try:
                            response_text = await response.text()
                            with open('/tmp/hypernym_debug.log', 'a') as f:
                                f.write(f"SYNC API ERROR: Sample {sample.id} got status {response.status}\n")
                                f.write(f"Response: {response_text}\n")
                        except:
                            response_text = "Could not read response"
                        raise Exception(f"Sync API returned {response.status}: {response_text}")
                    
                    result = await response.json()
                
                processing_time = time.time() - start_time
                
                # Extract compression ratio
                if 'results' in result:
                    v2_response = result['results']
                else:
                    v2_response = result
                
                segments = v2_response.get('response', {}).get('segments', [])
                
                # Check for no_results flag (Zone 1/2 responses)
                no_results = result.get('metadata', {}).get('no_results', False)
                
                if segments:
                    segment_ratios = [s.get('compression_ratio', 0) for s in segments]
                    actual_ratio = sum(segment_ratios) / len(segment_ratios) if segment_ratios else 0.0
                elif no_results:
                    # This is a valid Zone 1/2 response - short text that can't be compressed
                    # Set ratio to 1.0 (no compression) to indicate it's processed but not compressed
                    actual_ratio = 1.0
                else:
                    actual_ratio = 0.0
                
                # Extract similarity scores from segments
                avg_similarity = 0.75  # default
                if segments:
                    similarities = [s.get('semantic_similarity', 0.75) for s in segments if 'semantic_similarity' in s]
                    if similarities:
                        avg_similarity = sum(similarities) / len(similarities)
                
                # Track recent metrics for animation
                stats['recent_compressions'].append(actual_ratio)
                stats['recent_similarities'].append(avg_similarity)
                # Keep only last 10
                if len(stats['recent_compressions']) > 10:
                    stats['recent_compressions'].pop(0)
                if len(stats['recent_similarities']) > 10:
                    stats['recent_similarities'].pop(0)
                
                # Track ALL metrics for high scores
                stats['all_compressions'].append(actual_ratio)
                stats['all_similarities'].append(avg_similarity)
                
                # Update high scores
                if actual_ratio < stats['best_compression']:
                    stats['best_compression'] = actual_ratio
                if avg_similarity > stats['best_similarity']:
                    stats['best_similarity'] = avg_similarity
                
                # Save to cache
                processor._save_response(sample.id, request_hash, result, actual_ratio, processing_time)
                
                # Track by mode
                if analysis_mode == 'comprehensive':
                    stats['processed_comprehensive'] += 1
                    stats['session_comprehensive'] += 1
                else:
                    stats['processed_standard'] += 1
                    stats['session_standard'] += 1
                concurrency_mgr.record_success(processing_time)
                
                return {
                    'success': True,
                    'sample_id': sample.id,
                    'compression_ratio': actual_ratio,
                    'processing_time': processing_time,
                    'cached': False,
                    'response': result
                }
                
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)
                with open('/tmp/hypernym_debug.log', 'a') as f:
                    f.write(f"EXCEPTION: {error_type} for sample {sample.id}: {error_msg}\n")
                
                # Extract status code if available
                status_code = None
                if hasattr(e, 'status'):
                    status_code = e.status
                
                # Enhanced error message for 408 timeouts
                if status_code == 408:
                    error_msg = f"Server timeout (408) at {processor.api_url} - Server returned timeout status, not a client timeout. Content length: {len(sample.content)} bytes"
                elif status_code == 422:
                    error_msg = f"Content rejected (422) - Server cannot process this content type or size. Length: {len(sample.content)} bytes"
                
                # Handle 422 content errors separately - NEVER retry these
                if status_code == 422:
                    if DEBUG_SAMPLES:
                        print(f">>> CONTENT ERROR (422): Sample {sample.id} - {error_msg}")
                    stats['content_errors'] += 1
                else:
                    stats['errors'] += 1
                
                concurrency_mgr.record_error()
                
                if status_code == 422:
                    processor._save_content_error(
                        sample.id,
                        error_msg,
                        request_params={
                            'min_compression_ratio': compression_ratio,
                            'min_semantic_similarity': similarity,
                            'analysis_mode': analysis_mode,
                            'force_detail_count': force_detail_count,
                            'force_single_segment': force_single_segment
                        },
                        content_length=len(sample.content)
                    )
                    stats['content_errors'] = stats.get('content_errors', 0) + 1
                else:
                    # Save other errors to error_entries table (these can be retried)
                    processor._save_error(
                        sample.id,
                        error_type,
                        error_msg,
                        status_code=status_code,
                        request_params={
                            'min_compression_ratio': compression_ratio,
                            'min_semantic_similarity': similarity,
                            'analysis_mode': analysis_mode,
                            'force_detail_count': force_detail_count,
                            'force_single_segment': force_single_segment
                        },
                        attempt_number=1,  # Async version doesn't retry
                        content_length=len(sample.content)
                    )
                
                if worker_info:
                    worker_info['current_sample'] = f"Sample #{sample.id:04d} [red](failed: {str(e)})[/red]"
                    if worker_info['visible'] and worker_info['task_id'] is not None:
                        worker_progress.update(
                            worker_info['task_id'],
                            current_sample=worker_info['current_sample']
                        )
                return {
                    'success': False,
                    'sample_id': sample.id,
                    'error': str(e)
                }
        
        async def process_comprehensive_async(processor, session, sample, worker_info, 
                                            compression_ratio, similarity, timeout,
                                            force_detail_count, force_single_segment,
                                            include_embeddings, filters, request_hash):
            """Handle comprehensive mode with async API and progress tracking"""
            try:
                # Step 1: Start analysis with analyze_begin
                headers = {
                    'X-API-Key': processor.api_key,
                    'Content-Type': 'application/json'
                }
                
                params = {
                    'min_compression_ratio': compression_ratio,
                    'min_semantic_similarity': similarity,
                    'analysis_mode': 'comprehensive'
                }
                
                if force_detail_count is not None:
                    params['force_detail_count'] = force_detail_count
                if force_single_segment:
                    params['force_single_segment'] = force_single_segment
                if timeout != 600:
                    params['timeout'] = timeout
                if include_embeddings:
                    params['include_embeddings'] = include_embeddings
                if ensemble and processor.has_northstar_access():
                    params['ensemble'] = ensemble
                
                payload = {
                    'essay_text': sample.content,
                    'params': params
                }
                
                if filters:
                    payload['filters'] = filters
                
                # Start async analysis
                api_url_base = processor.api_url.rsplit('/', 1)[0]
                async_url = f"{api_url_base}/analyze_begin"
                
                start_time = time.time()
                
                async with session.post(async_url, headers=headers, json=payload) as response:
                    if response.status != 202:
                        text = await response.text()
                        raise Exception(f"Failed to start analysis: {text}")
                    
                    result = await response.json()
                    request_id = result['metadata']['request_id']
                
                # Update display
                if worker_info:
                    worker_info['current_sample'] = f"Sample #{sample.id:04d} [blue]COMP[/blue] [yellow]Starting...[/yellow]"
                    if worker_info['visible'] and worker_info['task_id'] is not None:
                        worker_progress.update(
                            worker_info['task_id'],
                            current_sample=worker_info['current_sample']
                        )
                
                # Step 2: Poll for progress
                status_url = f"{api_url_base}/analyze_status/{request_id}"
                poll_interval = 5  # seconds
                
                while True:
                    await asyncio.sleep(poll_interval)
                    
                    async with session.get(status_url, headers={'X-API-Key': processor.api_key}) as response:
                        if response.status != 200:
                            text = await response.text()
                            raise Exception(f"Status check failed: {text}")
                        
                        status_data = await response.json()
                        
                        # Check if still processing
                        if 'progress' in status_data:
                            progress = status_data['progress']
                            percent = progress.get('percent_complete', 0)
                            
                            # Update display with progress
                            if worker_info:
                                worker_info['current_sample'] = f"Sample #{sample.id:04d} [blue]COMP[/blue] [cyan]{percent}%[/cyan]"
                                if worker_info['visible'] and worker_info['task_id'] is not None:
                                    worker_progress.update(
                                        worker_info['task_id'],
                                        current_sample=worker_info['current_sample']
                                    )
                        
                        # Check if completed
                        elif (status_data.get('metadata', {}).get('status') == 'completed' or 
                              'response' in status_data or
                              status_data.get('metadata', {}).get('completed_at')):
                            # Analysis complete!
                            processing_time = time.time() - start_time
                            
                            # Extract results (same format as sync response)
                            result = status_data
                            
                            # Check for no_results flag (Zone 1/2 responses)
                            no_results = result.get('metadata', {}).get('no_results', False)
                            
                            # Extract compression ratio and similarity
                            segments = result.get('response', {}).get('segments', [])
                            
                            if segments:
                                segment_ratios = [s.get('compression_ratio', 0) for s in segments]
                                actual_ratio = sum(segment_ratios) / len(segment_ratios) if segment_ratios else 0.0
                                
                                similarities = [s.get('semantic_similarity', 0.75) for s in segments if 'semantic_similarity' in s]
                                avg_similarity = sum(similarities) / len(similarities) if similarities else 0.75
                            elif no_results:
                                # Valid Zone 1/2 response - short text that can't be compressed
                                actual_ratio = 1.0
                                avg_similarity = 1.0
                            else:
                                actual_ratio = 0.0
                                avg_similarity = 0.75
                            
                            # Update stats
                            stats['recent_compressions'].append(actual_ratio)
                            stats['recent_similarities'].append(avg_similarity)
                            if len(stats['recent_compressions']) > 10:
                                stats['recent_compressions'].pop(0)
                            if len(stats['recent_similarities']) > 10:
                                stats['recent_similarities'].pop(0)
                            
                            stats['all_compressions'].append(actual_ratio)
                            stats['all_similarities'].append(avg_similarity)
                            
                            if actual_ratio < stats['best_compression']:
                                stats['best_compression'] = actual_ratio
                            if avg_similarity > stats['best_similarity']:
                                stats['best_similarity'] = avg_similarity
                            
                            # Save to cache
                            processor._save_response(sample.id, request_hash, result, actual_ratio, processing_time)
                            
                            # Already counted elsewhere
                            stats['session_comprehensive'] += 1
                            concurrency_mgr.record_success(processing_time)
                            
                            return {
                                'success': True,
                                'sample_id': sample.id,
                                'compression_ratio': actual_ratio,
                                'processing_time': processing_time,
                                'cached': False,
                                'response': result
                            }
                        
                        # Check if failed
                        elif 'error' in status_data:
                            raise Exception(status_data['error'])
                
            except Exception as e:
                stats['errors'] += 1
                concurrency_mgr.record_error()
                error_msg = str(e)
                
                # Save error
                processor._save_error(
                    sample.id,
                    'ComprehensiveError',
                    error_msg,
                    request_params={
                        'min_compression_ratio': compression_ratio,
                        'min_semantic_similarity': similarity,
                        'analysis_mode': 'comprehensive',
                        'force_detail_count': force_detail_count,
                        'force_single_segment': force_single_segment
                    },
                    attempt_number=1,
                    content_length=len(sample.content)
                )
                
                if worker_info:
                    worker_info['current_sample'] = f"Sample #{sample.id:04d} [red](failed: {str(e)})[/red]"
                    if worker_info['visible'] and worker_info['task_id'] is not None:
                        worker_progress.update(
                            worker_info['task_id'],
                            current_sample=worker_info['current_sample']
                        )
                
                return {
                    'success': False,
                    'sample_id': sample.id,
                    'error': str(e)
                }
        
        async def update_worker_visibility():
            """Update which workers are visible based on scroll offset"""
            visible_start = stats['scroll_offset']
            visible_end = visible_start + max_display_workers
            
            # Clear all current tasks
            for task_id in worker_progress.task_ids:
                worker_progress.remove_task(task_id)
            
            # Add visible workers
            for i, worker_info in enumerate(all_worker_tasks):
                if visible_start <= i < visible_end:
                    task = worker_progress.add_task(
                        f"Worker {worker_info['id']}",
                        total=worker_info['total'],
                        completed=worker_info['completed'],
                        worker_name=f"Worker {worker_info['id']}",
                        current_sample=worker_info['current_sample']
                    )
                    worker_info['task_id'] = task
                    worker_info['visible'] = True
                else:
                    worker_info['visible'] = False
                    worker_info['task_id'] = None
        
        async def worker(processor, session, worker_id, queue, overall_task, samples_per_worker):
            """Worker coroutine"""
            worker_samples_processed = 0
            
            # Store task info for scrolling
            worker_info = {
                'id': worker_id,
                'visible': False,
                'task_id': None,
                'total': samples_per_worker,
                'completed': 0,
                'current_sample': "Starting..."
            }
            all_worker_tasks.append(worker_info)
            
            # Initial visibility check
            await update_worker_visibility()
            
            while True:
                # Check for shutdown request
                if processor._shutdown_requested:
                    worker_info['current_sample'] = "[yellow]Shutting down...[/yellow]"
                    if worker_info['visible'] and worker_info['task_id'] is not None:
                        worker_progress.update(
                            worker_info['task_id'],
                            current_sample=worker_info['current_sample']
                        )
                    break
                    
                try:
                    sample = await queue.get()
                    if sample is None:  # Stop signal
                        break
                    
                    if DEBUG_SAMPLES:
                        print(f">>> PROCESSING SAMPLE {sample.id}")
                    
                    # Process the sample
                    result = await process_sample_async(processor, session, sample, worker_id, worker_info['task_id'])
                    results[sample.id] = result
                    
                    # Update worker stats
                    worker_samples_processed += 1
                    worker_info['completed'] = worker_samples_processed
                    worker_info['current_sample'] = f"Sample #{sample.id:04d} [green](done)[/green]"
                    
                    # Update progress bar if visible
                    if worker_info['visible'] and worker_info['task_id'] is not None:
                        worker_progress.update(
                            worker_info['task_id'],
                            completed=worker_samples_processed,
                            current_sample=worker_info['current_sample'],
                            samples_count=worker_samples_processed
                        )
                    
                    # Update overall progress
                    overall_progress.advance(overall_task)
                    
                    queue.task_done()
                    
                except Exception as e:
                    worker_info['current_sample'] = f"[red]Error: {str(e)}[/red]"
                    if worker_info['visible'] and worker_info['task_id'] is not None:
                        worker_progress.update(
                            worker_info['task_id'],
                            current_sample=worker_info['current_sample']
                        )
            
            worker_info['current_sample'] = "[green]Complete[/green]"
            if worker_info['visible'] and worker_info['task_id'] is not None:
                worker_progress.update(
                    worker_info['task_id'],
                    current_sample=worker_info['current_sample']
                )
        
        # TRUST THE SQL QUERY - samples passed in are the ones to process
        # The main query already filtered by analysis_mode and cache status
        # Don't second-guess it with redundant cache checking
        samples_to_process = samples
        
        with open('/tmp/hypernym_debug.log', 'a') as f:
            f.write(f"SAMPLES TO PROCESS: {len(samples_to_process)} samples (trusting SQL query, no redundant filtering)\n")
        
        # Create overall task with correct count
        overall_task = overall_progress.add_task(
            "Processing samples",
            total=len(samples_to_process)
        )
        
        # Adjust worker count if we have fewer samples than workers
        actual_workers = min(max_workers, len(samples_to_process))
        
        # If nothing to process, return early
        if not samples_to_process:
            with open('/tmp/hypernym_debug.log', 'a') as f:
                f.write(f"NO SAMPLES TO PROCESS: All {len(samples)} samples were cached\n")
            # Convert results dict to list in original order
            processed_results = [results.get(s.id) for s in samples if s.id in results]
            return processed_results
        
        # Create work queue
        queue = asyncio.Queue()
        with open('/tmp/hypernym_debug.log', 'a') as f:
            f.write(f"QUEUE: Adding {len(samples_to_process)} samples to queue (filtered from {len(samples)} total)\n")
        for sample in samples_to_process:
            await queue.put(sample)
        
        # Add stop signals for each worker AFTER all samples
        for _ in range(actual_workers):
            await queue.put(None)
        
        # Set max scroll based on workers that won't fit
        stats['max_scroll'] = max(0, actual_workers - max_display_workers)
        
        # Create layout
        layout = make_layout(actual_workers, max_display_workers)
        
        # Create aiohttp session
        async with aiohttp.ClientSession() as session:
            # Query rate limits first
            console.print("🔍 Querying API rate limits...")
            limits = await concurrency_mgr.get_rate_limits(session)
            if limits:
                console.print(f"✅ Rate limits: {limits['limits']['requests_per_hour']:,}/hour, "
                            f"recommended {limits['recommended']['max_workers']} workers")
                console.print(f"🚀 Starting with {concurrency_mgr.current_workers} workers "
                            f"(will scale up to {concurrency_mgr.max_workers})")
            else:
                console.print(f"⚠️  Using default: {concurrency_mgr.current_workers} workers")
            
            await asyncio.sleep(1)  # Brief pause to read the info
            
            if ENABLE_LIVE_UI:
                with Live(layout, console=console, refresh_per_second=10):
                    # Start with adaptive number of workers
                    active_workers = min(concurrency_mgr.current_workers, actual_workers)
                    samples_per_worker = max(1, len(samples) // active_workers)
                    
                    workers = [
                        asyncio.create_task(worker(processor, session, i+1, queue, overall_task, samples_per_worker))
                        for i in range(active_workers)
                    ]
                    
                    # Update stats while processing
                    last_scroll = stats['scroll_offset']
                    while any(not w.done() for w in workers):
                        # Check for shutdown
                        if processor._shutdown_requested:
                            console.print("\n[yellow]🛑 Shutdown requested, waiting for workers to finish current samples...[/yellow]")
                            break
                            
                        stats['animation_frame'] += 1
                        
                        # Check if scroll position changed
                        if stats['scroll_offset'] != last_scroll:
                            await update_worker_visibility()
                            last_scroll = stats['scroll_offset']
                        
                        # Calculate visible range for dynamic panel title
                        visible_start = stats['scroll_offset']
                        visible_end = min(visible_start + max_display_workers, actual_workers)
                        
                        # Update progress section with banners
                        progress_left = Layout()
                        
                        # Create worker panel with scroll info
                        worker_panel_content = Layout()
                        
                        if actual_workers > max_display_workers:
                            # Add scroll indicators
                            scroll_text = f"Workers {visible_start+1}-{visible_end} of {actual_workers}"
                            if stats['scroll_offset'] > 0:
                                scroll_text += " (↑ more above)"
                            if stats['scroll_offset'] < stats['max_scroll']:
                                scroll_text += " (↓ more below)"
                            
                            worker_panel = Panel(
                                worker_progress,
                                title=f"[bold cyan]Processing Workers[/bold cyan] - {scroll_text}",
                                border_style="cyan"
                            )
                        else:
                            worker_panel = Panel(
                                worker_progress,
                                title="[bold cyan]Processing Workers[/bold cyan]",
                                border_style="cyan"
                            )
                        
                        worker_panel_content.update(worker_panel)
                        progress_left.update(worker_panel_content)
                        
                        # Create stats table
                        stats_table = Table(show_header=False, box=None, padding=(0, 1))
                        stats_table.add_column("Metric", style="bold")
                        stats_table.add_column("Value", justify="right")
                        
                        # Enhanced stats
                        stats_table.add_row("✓ Processed", f"[green]{stats['processed_standard'] + stats['processed_comprehensive']:,}[/green]")
                        stats_table.add_row("  Standard", f"[dim]{stats['processed_standard']:,}[/dim]")
                        stats_table.add_row("  Comprehensive", f"[blue]{stats['processed_comprehensive']:,}[/blue]")
                        stats_table.add_row("⚡ Cached", f"[yellow]{stats['cached']:,}[/yellow]")
                        stats_table.add_row("✗ Errors", f"[red]{stats['errors']:,}[/red]")
                        if stats['content_errors'] > 0:
                            stats_table.add_row("🚫 Content Rejected", f"[red]{stats['content_errors']:,}[/red]")
                        # Calculate rate from session stats
                        elapsed = time.time() - stats['start_time']
                        if elapsed > 0:
                            rate_per_min = (stats['session_standard'] + stats['session_comprehensive']) * 60 / elapsed
                            stats_table.add_row("⏱️ Rate", f"{rate_per_min:.1f}/min")
                        else:
                            stats_table.add_row("⏱️ Rate", "0.0/min")
                        
                        # Add performance metrics
                        if stats['recent_compressions']:
                            avg_comp = sum(stats['recent_compressions']) / len(stats['recent_compressions'])
                            stats_table.add_row("📊 Avg Compression", f"{avg_comp:.1%}")
                        
                        if stats['recent_similarities']:
                            avg_sim = sum(stats['recent_similarities']) / len(stats['recent_similarities'])
                            stats_table.add_row("🎯 Avg Similarity", f"{avg_sim:.1%}")
                        
                        stats_panel = Panel(
                            Align.center(stats_table),
                            title="[bold green]Statistics[/bold green]",
                            border_style="green"
                        )
                        
                        # Create progress content
                        progress_content = Layout()
                        progress_content.split_row(
                            progress_left,
                            stats_panel
                        )
                        
                        layout["progress"].update(progress_content)
                        
                        await asyncio.sleep(0.1)
                    
                    # Wait for all workers to complete
                    await asyncio.gather(*workers)
            else:
                # No Live UI - just run workers
                active_workers = min(concurrency_mgr.current_workers, actual_workers)
                samples_per_worker = max(1, len(samples) // active_workers)
                
                workers = [
                    asyncio.create_task(worker(processor, session, i+1, queue, overall_task, samples_per_worker))
                    for i in range(active_workers)
                ]
                
                # Wait for all workers to complete
                await asyncio.gather(*workers)
                
                # Update stats while processing
                last_scroll = stats['scroll_offset']
                while any(not w.done() for w in workers):
                    # Check for shutdown
                    if processor._shutdown_requested:
                        console.print("\n[yellow]🛑 Shutdown requested, waiting for workers to finish current samples...[/yellow]")
                        break
                        
                    stats['animation_frame'] += 1
                    
                    # Check if scroll position changed
                    if stats['scroll_offset'] != last_scroll:
                        await update_worker_visibility()
                        last_scroll = stats['scroll_offset']
                    
                    # Calculate visible range for dynamic panel title
                    visible_start = stats['scroll_offset']
                    visible_end = min(visible_start + max_display_workers, actual_workers)
                    
                    # Update progress section with banners
                    progress_left = Layout()
                    
                    # Create worker panel with scroll info
                    if actual_workers > max_display_workers:
                        position_text = f"[{visible_start+1}-{visible_end}/{actual_workers}]"
                        scroll_info = "↑/↓: scroll 1 | PgUp/PgDn: scroll 18"
                        worker_panel = Panel(
                            worker_progress,
                            border_style="cyan",
                            title=f"[bold cyan]Workers {position_text}[/bold cyan]",
                            subtitle=f"[dim]{scroll_info}[/dim]"
                        )
                    else:
                        worker_panel = Panel(worker_progress, border_style="cyan")
                    
                    progress_left.split_column(
                        Layout(Panel(overall_progress, border_style="green"), size=3),
                        Layout(worker_panel)
                    )
                    
                    progress_content = Layout()
                    progress_content.split_row(
                        Layout(progress_left, ratio=3),
                        Layout(
                            Panel(
                                Align.center(create_average_banners(), vertical="middle"),
                                title="[bold magenta]📊 Performance Meters 📊[/bold magenta]",
                                border_style="magenta"
                            ),
                            ratio=1
                        )
                    )
                    layout["progress"].update(progress_content)
                    
                    # Update stats panel
                    layout["stats"].update(
                        Panel(
                            Align.center(make_stats_table(), vertical="middle"),
                            title="[bold]Statistics[/bold]",
                            border_style="yellow"
                        )
                    )
                    
                    # Update best scores panel
                    layout["best_scores"].update(
                        Panel(
                            Align.center(create_best_scores_display(), vertical="middle"),
                            title="[bold]🏆 High Scores 🏆[/bold]",
                            border_style="green"
                        )
                    )
                    
                    await asyncio.sleep(0.1)
                
                # Wait for workers
                await asyncio.gather(*workers)
                
                # Final stats update
                layout["stats"].update(
                    Panel(
                        Align.center(make_stats_table(), vertical="middle"),
                        title="[bold]Statistics - Complete[/bold]",
                        border_style="green"
                    )
                )
                
                # Final best scores update
                layout["best_scores"].update(
                    Panel(
                        Align.center(create_best_scores_display(), vertical="middle"),
                        title="[bold]🏆 Final High Scores 🏆[/bold]",
                        border_style="green"
                    )
                )
                
                await asyncio.sleep(1)
        
        # Convert results dict to list in original order
        processed_results = [results.get(s.id) for s in samples if s.id in results]
        
        # If shutdown was requested, print summary
        if processor._shutdown_requested:
            console.print(f"\n[yellow]⚠️  Shutdown complete. Processed {len(processed_results)}/{len(samples)} samples[/yellow]")
        
        return processed_results

