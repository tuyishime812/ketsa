$path = 'C:\Users\Administrator\Desktop\shift project\ketsa\backend\app\models.py'
$c = Get-Content $path
for($i=0;$i<$c.Length;$i++){
  if($c[$i] -match 'TradeRequest'){
    for($j=$i-10;$j -lt $i+80 -and $j -lt $c.Length;$j++){
      if($j -ge 0){ Write-Host "$($j+1): $($c[$j])" }
    }
    break
  }
}