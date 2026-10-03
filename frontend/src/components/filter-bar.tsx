import { Button } from '@/components/ui/button'

interface FilterBarProps {
  value: string | undefined
  onChange: (value: string | undefined) => void
  options: { value: string | undefined; label: string }[]
}

export function FilterBar({ value, onChange, options }: FilterBarProps) {
  return (
    <div className="bg-muted flex w-fit rounded-lg p-0.5" role="group">
      {options.map((option) => (
        <Button
          key={option.label}
          size="sm"
          variant={option.value === value ? 'default' : 'ghost'}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  )
}
