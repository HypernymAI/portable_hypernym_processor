#!/usr/bin/env python3
"""
Demo of pretty parallel progress bars for multiprocessing
Shows how the CLI output will look with multiple workers
"""

import asyncio
import random
import time
from datetime import datetime, timedelta
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn
from rich.table import Table
from rich.align import Align

class ParallelProgressDemo:
    def __init__(self, num_workers=4, total_samples=100):
        self.num_workers = num_workers
        self.total_samples = total_samples
        self.console = Console()
        
        # Create progress bars
        self.overall_progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Overall Progress"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=self.console,
            expand=False
        )
        
        self.worker_progress = Progress(
            TextColumn("[bold cyan]{task.fields[worker_name]:>10}"),
            SpinnerColumn(),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[current_sample]}"),
            console=self.console,
            expand=False
        )
        
        # Stats tracking
        self.stats = {
            'processed': 0,
            'errors': 0,
            'cache_hits': 0,
            'rate_limited': 0,
            'start_time': time.time()
        }
        
    def make_stats_table(self):
        """Create a pretty stats table"""
        table = Table(show_header=False, box=None, padding=(0, 2))
        
        # Calculate rate
        elapsed = time.time() - self.stats['start_time']
        rate = self.stats['processed'] / elapsed if elapsed > 0 else 0
        
        # Add stats
        table.add_row("[green]✓ Processed", f"[bold green]{self.stats['processed']:,}")
        table.add_row("[yellow]⚡ Cache Hits", f"[bold yellow]{self.stats['cache_hits']:,}")
        table.add_row("[red]✗ Errors", f"[bold red]{self.stats['errors']:,}")
        table.add_row("[magenta]⏱ Rate Limited", f"[bold magenta]{self.stats['rate_limited']:,}")
        table.add_row("[blue]⚡ Rate", f"[bold blue]{rate:.1f}/sec")
        
        return table
    
    def make_layout(self):
        """Create the layout"""
        layout = Layout()
        
        # Split into sections
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="progress", size=self.num_workers + 3),
            Layout(name="stats", size=8)
        )
        
        # Header
        layout["header"].update(
            Panel(
                Align.center(
                    f"[bold]Hypernym Parallel Processor[/bold]\n"
                    f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
                    vertical="middle"
                ),
                border_style="blue"
            )
        )
        
        # Progress bars
        progress_group = Layout()
        progress_group.split_column(
            Layout(Panel(self.overall_progress, border_style="green"), size=3),
            Layout(Panel(self.worker_progress, border_style="cyan"))
        )
        layout["progress"].update(progress_group)
        
        # Stats
        layout["stats"].update(
            Panel(
                Align.center(self.make_stats_table(), vertical="middle"),
                title="[bold]Statistics[/bold]",
                border_style="yellow"
            )
        )
        
        return layout
    
    async def simulate_sample_processing(self, sample_id, worker_id, worker_task):
        """Simulate processing a single sample"""
        # Update worker status
        self.worker_progress.update(
            worker_task,
            current_sample=f"Sample #{sample_id:04d}"
        )
        
        # Simulate processing time (0.5 - 3 seconds)
        processing_time = random.uniform(0.5, 3.0)
        
        # Simulate different outcomes
        outcome = random.choices(
            ['success', 'cache_hit', 'error', 'rate_limit'],
            weights=[70, 20, 5, 5],
            k=1
        )[0]
        
        # Animate progress
        steps = 20
        for i in range(steps):
            self.worker_progress.update(worker_task, completed=i+1)
            await asyncio.sleep(processing_time / steps)
            
            # Simulate occasional pauses
            if random.random() < 0.1:
                self.worker_progress.update(
                    worker_task,
                    current_sample=f"Sample #{sample_id:04d} [yellow](retrying...)[/yellow]"
                )
                await asyncio.sleep(0.5)
        
        # Update stats based on outcome
        if outcome == 'success':
            self.stats['processed'] += 1
        elif outcome == 'cache_hit':
            self.stats['processed'] += 1
            self.stats['cache_hits'] += 1
        elif outcome == 'error':
            self.stats['errors'] += 1
            self.worker_progress.update(
                worker_task,
                current_sample=f"Sample #{sample_id:04d} [red](failed)[/red]"
            )
            await asyncio.sleep(0.5)
        elif outcome == 'rate_limit':
            self.stats['rate_limited'] += 1
            self.worker_progress.update(
                worker_task,
                current_sample=f"Sample #{sample_id:04d} [magenta](rate limited)[/magenta]"
            )
            await asyncio.sleep(2.0)  # Longer pause for rate limit
        
        # Reset worker progress for next sample
        self.worker_progress.update(worker_task, completed=0)
        
        return outcome
    
    async def worker(self, worker_id, queue, overall_task):
        """Worker coroutine"""
        # Create worker task
        worker_task = self.worker_progress.add_task(
            f"Worker {worker_id}",
            total=20,
            worker_name=f"Worker {worker_id}",
            current_sample="Starting..."
        )
        
        while True:
            try:
                sample_id = await queue.get()
                if sample_id is None:  # Poison pill
                    break
                
                # Process the sample
                await self.simulate_sample_processing(sample_id, worker_id, worker_task)
                
                # Update overall progress
                self.overall_progress.advance(overall_task)
                
                queue.task_done()
                
            except Exception as e:
                self.worker_progress.update(
                    worker_task,
                    current_sample=f"[red]Error: {str(e)}[/red]"
                )
        
        # Clean up
        self.worker_progress.update(
            worker_task,
            current_sample="[green]Complete[/green]"
        )
    
    async def run(self):
        """Run the demo"""
        # Create overall task
        overall_task = self.overall_progress.add_task(
            "Processing samples",
            total=self.total_samples
        )
        
        # Create work queue
        queue = asyncio.Queue()
        for i in range(1, self.total_samples + 1):
            await queue.put(i)
        
        # Create layout
        layout = self.make_layout()
        
        # Start display and workers
        with Live(layout, console=self.console, refresh_per_second=10):
            # Start workers
            workers = [
                asyncio.create_task(self.worker(i+1, queue, overall_task))
                for i in range(self.num_workers)
            ]
            
            # Update stats while processing
            while not queue.empty() or any(not w.done() for w in workers):
                layout["stats"].update(
                    Panel(
                        Align.center(self.make_stats_table(), vertical="middle"),
                        title="[bold]Statistics[/bold]",
                        border_style="yellow"
                    )
                )
                await asyncio.sleep(0.1)
            
            # Send poison pills
            for _ in range(self.num_workers):
                await queue.put(None)
            
            # Wait for workers
            await asyncio.gather(*workers)
            
            # Final stats update
            layout["stats"].update(
                Panel(
                    Align.center(self.make_stats_table(), vertical="middle"),
                    title="[bold]Statistics - Complete[/bold]",
                    border_style="green"
                )
            )
            
            await asyncio.sleep(2)  # Show final state

async def main():
    """Run the demo"""
    print("\n" * 50)  # Clear screen space
    demo = ParallelProgressDemo(num_workers=4, total_samples=50)
    await demo.run()
    print("\n✅ Demo complete!\n")

if __name__ == "__main__":
    asyncio.run(main())