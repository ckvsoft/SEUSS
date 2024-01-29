#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024 Christian Kvasny chris(at)ckvsoft.at
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#  THE SOFTWARE.
#
#  Project: [SEUSS -> Smart Ess Unit Spotmarket Switcher
#

class DynamicValueCalculator:

    def __init__(self):
        pass

    def adjust_value_increase(self, current_value, min_value, max_value, influence_value, increase=True):
        """
        Adjusts the current value based on the influence value.

        Parameters:
        - current_value (float): The current value to be adjusted.
        - min_value (float): The minimum limit of the current value.
        - max_value (float): The maximum limit of the current value.
        - influence_value (float): The influencing value ranging from 10% to 90%.
        - increase True,  decrease False

        Returns:
        - float: The adjusted value.
        """
        # Validate input
        if not (min_value <= current_value <= max_value) or not (0 <= influence_value <= 100):
            raise ValueError("Invalid input values")

        # Calculate the adjustment range
        adjustment_range = max_value - min_value

        # Calculate the adjustment amount based on the influence value
        if increase:
            adjustment_amount = (influence_value - 50) / 50 * adjustment_range
        else:
            adjustment_amount = (50 - influence_value) / 50 * adjustment_range

        # Adjust the current value
        adjusted_value = current_value + adjustment_amount

        # Clip the adjusted value to be within the specified range
        adjusted_value = max(min_value, min(adjusted_value, max_value))

        return adjusted_value

    def find_max_y_with_empty_result(self, func, min_y, max_y, tolerance=0.01):
        """
        Finds the maximum y such that the given function produces an empty result.

        Parameters:
        - func (callable): The function to be evaluated. It should take a single argument.
        - min_y (float): The minimum value for y.
        - max_y (float): The maximum value for y.
        - tolerance (float): Tolerance level for the binary search. Default is 0.01.

        Returns:
        - float: The maximum y value with an empty result.
        """
        # Binary search
        while max_y - min_y > tolerance:
            mid_y = (min_y + max_y) / 2
            result = func(mid_y)

            if not result:
                max_y = mid_y
            else:
                min_y = mid_y

        return max_y
