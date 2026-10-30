import { describe, it, expect } from 'vitest';
import { buildPopupContent, buildPinElement, getDepartmentColor } from '@/components/civic/LocationMap';

describe('LocationMap XSS prevention', () => {
  it('does not create <img> or <script> elements from malicious title', () => {
    const maliciousRow = {
      id: '42',
      title: '<img src=x onerror=alert(1)>',
      department: 'Roads & Bridges',
      category: 'Roads & footpaths' as const,
      address: '123 Main St',
      ward: 'Ward 5',
      status: 'submitted',
    };
    const color = getDepartmentColor(maliciousRow.department);
    const popup = buildPopupContent(maliciousRow, color);

    // No <img> or <script> elements should be created
    expect(popup.querySelectorAll('img')).toHaveLength(0);
    expect(popup.querySelectorAll('script')).toHaveLength(0);

    // The malicious string should appear as literal text
    expect(popup.textContent).toContain('<img src=x onerror=alert(1)>');
  });

  it('does not create <script> elements from malicious department', () => {
    const maliciousRow = {
      id: '99',
      title: 'Normal title',
      department: '<script>alert("xss")</script>',
      address: '<img src=x onerror=alert(2)>',
      ward: 'Ward 1',
      status: 'in_progress',
    };
    const color = getDepartmentColor(maliciousRow.department);
    const popup = buildPopupContent(maliciousRow, color);

    expect(popup.querySelectorAll('script')).toHaveLength(0);
    expect(popup.querySelectorAll('img')).toHaveLength(0);
    expect(popup.textContent).toContain('<script>alert("xss")</script>');
    expect(popup.textContent).toContain('<img src=x onerror=alert(2)>');
  });

  it('encodes complaint id in the link href', () => {
    const row = {
      id: 'abc/../../etc/passwd',
      title: 'Test',
      department: 'Water Supply',
      status: 'submitted',
    };
    const color = getDepartmentColor(row.department);
    const popup = buildPopupContent(row, color);
    const link = popup.querySelector('a');

    expect(link).not.toBeNull();
    expect(link!.href).toContain(encodeURIComponent('abc/../../etc/passwd'));
    // Should NOT contain un-encoded slashes from the id
    expect(link!.getAttribute('href')).toBe(
      `/complaints/${encodeURIComponent('abc/../../etc/passwd')}`,
    );
  });

  it('renders status with underscore replaced by space', () => {
    const row = {
      id: '1',
      title: 'Test',
      department: 'Water Supply',
      status: 'in_progress',
    };
    const color = getDepartmentColor(row.department);
    const popup = buildPopupContent(row, color);

    expect(popup.textContent).toContain('in progress');
  });

  it('getDepartmentColor returns only allowlisted hex colors', () => {
    const allowedColors = new Set([
      '#ea580c', '#06b6d4', '#0284c7', '#eab308', '#16a34a', '#9333ea', '#64748b',
    ]);

    // Malicious input should fall back to default
    expect(allowedColors.has(getDepartmentColor('<script>alert(1)</script>'))).toBe(true);
    expect(allowedColors.has(getDepartmentColor(undefined))).toBe(true);
    expect(allowedColors.has(getDepartmentColor('Water Supply'))).toBe(true);
    expect(allowedColors.has(getDepartmentColor('anything random'))).toBe(true);
  });

  it('buildPinElement creates a valid DOM element with no user content', () => {
    const pin = buildPinElement('#ea580c');
    expect(pin.tagName).toBe('DIV');
    expect(pin.children).toHaveLength(1);
    expect(pin.querySelector('script')).toBeNull();
    expect(pin.querySelector('img')).toBeNull();
  });
});
