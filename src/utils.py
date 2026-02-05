
import math

def format_deck_name(name):
    # Just capitalize first letter of words
    return name.title()

def format_percentage(val):
    return f"{val:.1f}%"

def calculate_confidence_interval(wins, total, z=1.96):
    """
    Calculate the Wilson score interval for a binomial proportion.
    
    Args:
        wins: Number of successes (wins)
        total: Total number of trials (matches)
        z: Z-score for confidence level (1.96 for 95%)
        
    Returns:
        tuple: (lower_bound_percentage, upper_bound_percentage)
    """
    if total == 0:
        return 0.0, 0.0
        
    p = wins / total
    
    denominator = 1 + z**2 / total
    center_adjusted_probability = p + z**2 / (2 * total)
    adjusted_standard_deviation = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
    
    lower_bound = (center_adjusted_probability - adjusted_standard_deviation) / denominator
    upper_bound = (center_adjusted_probability + adjusted_standard_deviation) / denominator
    
    # Clamp to [0, 1] and convert to percentage
    lower_bound = max(0.0, min(lower_bound, 1.0)) * 100
    upper_bound = max(0.0, min(upper_bound, 1.0)) * 100
    
    return lower_bound, upper_bound

def calculate_bayesian_win_probability(wins, total):
    """
    Calculate the probability that the true win rate is > 50% using Bayesian estimation.
    Assumes a Beta(1,1) prior, so the posterior is Beta(wins+1, total-wins+1).
    We use a normal approximation for $P(X > 0.5)$.
    """
    if total == 0:
        return 50.0 # Neutral

    # For Beta(a, b):
    # Mean = a / (a + b)
    # Var = ab / ((a+b)^2 * (a+b+1))
    a = wins + 1
    b = (total - wins) + 1
    
    mean = a / (a + b)
    var = (a * b) / ((a + b)**2 * (a + b + 1))
    sd = math.sqrt(var)
    
    if sd == 0:
        return 100.0 if mean > 0.5 else 0.0
    
    # Z-score for 0.5
    z = (0.5 - mean) / sd
    
    # Normal CDF approximation using erf
    # Phi(x) = 0.5 * (1 + erf(x / sqrt(2)))
    def phi(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    
    # Probability (X > 0.5) = 1 - Phi(z) = Phi(-z)
    prob = phi(-z)
    return prob * 100
