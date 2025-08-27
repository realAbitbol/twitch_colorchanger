"""
Memory leak monitoring for HTTP client
"""
import gc
from typing import Dict, Any
from src.logger import BotLogger

logger = BotLogger(__name__)


class MemoryMonitor:
    """Monitor for potential memory leaks in HTTP client"""
    
    def __init__(self):
        self.baseline_objects = {}
        self.baseline_set = False
    
    def set_baseline(self):
        """Set baseline memory usage for comparison"""
        gc.collect()  # Force garbage collection
        self.baseline_objects = self._count_objects()
        self.baseline_set = True
        logger.debug("Memory baseline set", extra={'objects': self.baseline_objects})
    
    def check_leaks(self) -> Dict[str, Any]:
        """Check for potential memory leaks compared to baseline"""
        if not self.baseline_set:
            logger.warning("Memory baseline not set, setting it now")
            self.set_baseline()
            return {'status': 'baseline_set'}
        
        gc.collect()  # Force garbage collection
        current_objects = self._count_objects()
        
        leaks = {}
        significant_increases = {}
        
        for obj_type, current_count in current_objects.items():
            baseline_count = self.baseline_objects.get(obj_type, 0)
            increase = current_count - baseline_count
            
            # Flag significant increases (more than 50% or more than 10 objects)
            if increase > max(baseline_count * 0.5, 10):
                significant_increases[obj_type] = {
                    'baseline': baseline_count,
                    'current': current_count,
                    'increase': increase,
                    'percentage': (increase / baseline_count * 100) if baseline_count > 0 else float('inf')
                }
        
        # Check for specific HTTP-related objects
        http_related = [
            'ClientSession', 'TCPConnector', 'aiohttp', 'ssl.SSLContext',
            'socket.socket', '_SSLSocket', 'asyncio'
        ]
        
        for obj_type in http_related:
            if obj_type in significant_increases:
                leaks[obj_type] = significant_increases[obj_type]
        
        result = {
            'status': 'checked',
            'total_objects': sum(current_objects.values()),
            'baseline_objects': sum(self.baseline_objects.values()),
            'object_increase': sum(current_objects.values()) - sum(self.baseline_objects.values()),
            'potential_leaks': leaks,
            'significant_increases': significant_increases
        }
        
        if leaks:
            logger.warning("Potential memory leaks detected", extra=result)
        else:
            logger.debug("No significant memory leaks detected", extra=result)
        
        return result
    
    def _count_objects(self) -> Dict[str, int]:
        """Count objects by type"""
        object_counts = {}
        
        for obj in gc.get_objects():
            obj_type = type(obj).__name__
            if hasattr(type(obj), '__module__'):
                module = type(obj).__module__
                if module and module != 'builtins':
                    obj_type = f"{module}.{obj_type}"
            
            object_counts[obj_type] = object_counts.get(obj_type, 0) + 1
        
        return object_counts


# Global memory monitor instance
_memory_monitor = MemoryMonitor()


def check_memory_leaks() -> Dict[str, Any]:
    """Quick function to check for memory leaks"""
    return _memory_monitor.check_leaks()
